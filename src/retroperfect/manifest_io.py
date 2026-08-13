from __future__ import annotations

import csv
import hashlib
import html
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from .models import ActionMode, Manifest
from .patching import download_and_apply_patch
from .paths import project_state_dir


def save_manifest(manifest: Manifest, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


HASH_CHUNK_SIZE = 1024 * 1024


def preflight_manifest(manifest: Manifest) -> list[str]:
    """Comprueba orígenes, colisiones de destino y espacio en disco antes de aplicar."""
    issues: list[str] = []
    destinations: dict[str, str] = {}
    needed_by_device: dict[int, int] = {}
    device_roots: dict[int, Path] = {}
    for entry in manifest.entries:
        source = Path(entry.source_path)
        if not source.exists():
            issues.append(f"Origen no encontrado: {source}")
            continue
        if not entry.destination_path:
            continue
        previous = destinations.get(entry.destination_path)
        if previous is not None and previous != entry.source_path:
            issues.append(f"Colisión de destino: {entry.destination_path} recibiría {previous} y también {entry.source_path}")
        destinations[entry.destination_path] = entry.source_path
        root = _existing_ancestor(Path(entry.destination_path))
        device = os.stat(root).st_dev
        cross_device_move = entry.action == ActionMode.MOVE and os.stat(source).st_dev != device
        if bool(entry.patch_url) or entry.action == ActionMode.COPY or cross_device_move:
            needed_by_device[device] = needed_by_device.get(device, 0) + source.stat().st_size
            device_roots.setdefault(device, root)
    for device, needed in needed_by_device.items():
        root = device_roots[device]
        free = shutil.disk_usage(root).free
        if needed > free:
            issues.append(f"Espacio insuficiente en {root}: se necesitan {_human_size(needed)} y quedan {_human_size(free)} libres.")
    return issues


def _existing_ancestor(path: Path) -> Path:
    for candidate in [path, *path.parents]:
        if candidate.exists():
            return candidate
    return Path(path.anchor or ".")


def _human_size(value: int) -> str:
    size = float(value)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def apply_manifest(
    manifest: Manifest,
    mode: ActionMode | None = None,
    confirm: bool = False,
    verify: bool = True,
    hard_delete: bool = False,
    trash_dir: Path | None = None,
) -> list[str]:
    if not confirm:
        raise RuntimeError("No se aplica el manifiesto sin confirmación explícita.")
    issues = preflight_manifest(manifest)
    if issues:
        raise RuntimeError("No se puede aplicar el manifiesto:\n- " + "\n- ".join(issues))
    session_trash: Path | None = None
    completed: list[str] = []
    seen: set[tuple[str, str | None, ActionMode]] = set()
    for entry in manifest.entries:
        action = entry.action
        if mode is not None and mode != action:
            raise RuntimeError(
                f"El manifiesto se planificó con acción '{action.value}' pero se pidió aplicar '{mode.value}'. Regenera el plan con la acción deseada."
            )
        source = Path(entry.source_path)
        destination = Path(entry.destination_path) if entry.destination_path else None
        key = (str(source), str(destination) if destination else None, action)
        if key in seen:
            continue
        seen.add(key)
        if entry.patch_url:
            if action == ActionMode.DELETE:
                completed.append(f"parche omitido en modo borrado: {source}")
                continue
            if not destination:
                raise RuntimeError(f"La acción de parcheo necesita un destino para {source}")
            source_data = _read_entry_source(entry.source_path, entry.source_inner_path)
            patched, patch = download_and_apply_patch(source_data, entry.patch_url)
            patched_md5 = hashlib.md5(patched).hexdigest()
            if entry.patch_expected_md5 and patched_md5.lower() != entry.patch_expected_md5.lower():
                raise RuntimeError(
                    f"El hash del ROM parcheado no coincide para {source}: se esperaba {entry.patch_expected_md5} y se obtuvo {patched_md5}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(patched)
            if verify:
                _verify_destination(destination, patched_md5, source)
                completed.append(f"parcheado {source} con {patch.name} -> {destination} (md5 verificado)")
            else:
                completed.append(f"parcheado {source} con {patch.name} -> {destination}")
            continue
        if action == ActionMode.COPY:
            if not destination:
                raise RuntimeError(f"La acción de copia necesita un destino para {source}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if verify:
                source_md5 = _copy_hashing(source, destination)
                _check_source_md5(entry, source_md5)
                _verify_destination(destination, source_md5, source)
                completed.append(f"copiado {source} -> {destination} (md5 verificado)")
            else:
                shutil.copy2(source, destination)
                completed.append(f"copiado {source} -> {destination}")
        elif action == ActionMode.MOVE:
            if not destination:
                raise RuntimeError(f"La acción de mover necesita un destino para {source}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            move_md5 = _file_md5(source) if verify else None
            if move_md5 is not None:
                _check_source_md5(entry, move_md5)
            shutil.move(str(source), str(destination))
            if move_md5 is not None:
                _verify_destination(destination, move_md5, source)
                completed.append(f"movido {source} -> {destination} (md5 verificado)")
            else:
                completed.append(f"movido {source} -> {destination}")
        elif action == ActionMode.DELETE:
            if hard_delete:
                source.unlink()
                completed.append(f"borrado definitivo {source}")
            else:
                if session_trash is None:
                    root = trash_dir or (project_state_dir() / "trash")
                    session_trash = root / datetime.now().strftime("%Y%m%d-%H%M%S")
                    session_trash.mkdir(parents=True, exist_ok=True)
                target = _trash_target(session_trash, source.name)
                shutil.move(str(source), str(target))
                completed.append(f"movido a papelera {source} -> {target}")
    return completed


def _trash_target(trash_session: Path, name: str) -> Path:
    target = trash_session / name
    counter = 1
    while target.exists():
        counter += 1
        target = trash_session / f"{Path(name).stem} ({counter}){Path(name).suffix}"
    return target


def _file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        while chunk := fh.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_hashing(source: Path, destination: Path) -> str:
    """Copia por chunks calculando el MD5 del origen en la misma pasada."""
    digest = hashlib.md5()
    with source.open("rb") as src, destination.open("wb") as dst:
        while chunk := src.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
            dst.write(chunk)
    shutil.copystat(source, destination)
    return digest.hexdigest()


def _check_source_md5(entry, source_md5: str) -> None:
    if entry.source_md5 and source_md5 != entry.source_md5.lower():
        raise RuntimeError(
            f"El origen {entry.source_path} cambió desde el escaneo (MD5 esperado {entry.source_md5}, actual {source_md5}). Reescanea y regenera el plan."
        )


def _verify_destination(destination: Path, expected_md5: str, source: Path) -> None:
    destination_md5 = _file_md5(destination)
    if destination_md5 != expected_md5:
        raise RuntimeError(
            f"Verificación fallida: {destination} (MD5 {destination_md5}) no coincide con el origen {source} (MD5 {expected_md5})."
        )


def _read_entry_source(source_path: str, inner_path: str | None) -> bytes:
    source = Path(source_path)
    if inner_path:
        with zipfile.ZipFile(source) as archive:
            return archive.read(inner_path)
    return source.read_bytes()


def report_manifest(manifest: Manifest, path: Path, fmt: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    elif fmt == "csv":
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["bucket", "action", "source_path", "source_inner_path", "destination_path", "dat_name", "ra_game_id", "patch_url", "patch_expected_md5", "explanation"],
            )
            writer.writeheader()
            for entry in manifest.entries:
                writer.writerow(
                    {
                        "bucket": entry.bucket.value,
                        "action": entry.action.value,
                        "source_path": entry.source_path,
                        "source_inner_path": entry.source_inner_path or "",
                        "destination_path": entry.destination_path or "",
                        "dat_name": entry.dat_name or "",
                        "ra_game_id": entry.ra_game_id or "",
                        "patch_url": entry.patch_url or "",
                        "patch_expected_md5": entry.patch_expected_md5 or "",
                        "explanation": " | ".join(entry.explanation),
                    }
                )
    elif fmt == "html":
        total = len(manifest.entries)
        buckets: dict[str, int] = {}
        patched = 0
        for entry in manifest.entries:
            buckets[entry.bucket.value] = buckets.get(entry.bucket.value, 0) + 1
            if entry.patch_url:
                patched += 1
        rows = "\n".join(
            "<tr>"
            f"<td><span class='pill'>{html.escape(entry.bucket.value)}</span></td>"
            f"<td>{html.escape(entry.action.value)}</td>"
            f"<td>{html.escape(Path(entry.source_path).name)}</td>"
            f"<td>{html.escape(entry.source_inner_path or '')}</td>"
            f"<td>{html.escape(entry.destination_path or '')}</td>"
            f"<td>{html.escape(entry.dat_name or '')}</td>"
            f"<td>{html.escape(str(entry.ra_game_id or ''))}</td>"
            f"<td>{'yes' if entry.patch_url else ''}</td>"
            f"<td>{html.escape(entry.patch_expected_md5 or '')}</td>"
            f"<td>{html.escape(' | '.join(entry.explanation))}</td>"
            "</tr>"
            for entry in manifest.entries
        )
        cards = "".join(f"<div class='metric'><strong>{count}</strong><span>{html.escape(bucket)}</span></div>" for bucket, count in sorted(buckets.items()))
        path.write_text(
            f"""<!doctype html>
<html><head><meta charset="utf-8"><title>RetroPerfect Report</title>
<style>
body{{font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,sans-serif;margin:0;background:#f6f7f8;color:#172326}}
header{{background:#276a73;color:white;padding:2rem 2.5rem}}
main{{padding:2rem 2.5rem}}
h1{{margin:.2rem 0;font-size:2rem}} .sub{{opacity:.8}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.8rem;margin:1.5rem 0}}
.metric{{background:white;border:1px solid #d8e1e4;border-radius:8px;padding:1rem}}
.metric strong{{display:block;font-size:1.6rem;color:#276a73}} .metric span{{color:#56636a}}
table{{border-collapse:collapse;width:100%;background:white;border:1px solid #d8e1e4;border-radius:8px;overflow:hidden}}
td,th{{border-bottom:1px solid #e4eaec;padding:.55rem;vertical-align:top;font-size:.88rem}}th{{background:#eef7f8;text-align:left}}
.pill{{background:#e6f4ea;color:#137333;border-radius:999px;padding:.15rem .5rem;font-weight:600}}
</style></head>
<body><header><h1>RetroPerfect Report</h1><div class="sub">Manifest {html.escape(manifest.id)} · {html.escape(manifest.platform.value)} · {html.escape(manifest.created_at.isoformat())}</div></header>
<main><div class="metrics"><div class="metric"><strong>{total}</strong><span>operaciones</span></div><div class="metric"><strong>{patched}</strong><span>parches RA</span></div>{cards}</div>
<table><thead><tr><th>Salida</th><th>Acción</th><th>Origen</th><th>Inner</th><th>Destino</th><th>DAT</th><th>RA</th><th>Patch</th><th>MD5 esperado</th><th>Motivo</th></tr></thead><tbody>{rows}</tbody></table></main></body></html>""",
            encoding="utf-8",
        )
    else:
        raise ValueError(f"Formato de reporte no soportado: {fmt}")
    return path
