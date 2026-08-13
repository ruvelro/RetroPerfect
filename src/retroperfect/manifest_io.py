from __future__ import annotations

import csv
import hashlib
import html
import json
import shutil
import zipfile
from pathlib import Path

from .models import ActionMode, Manifest
from .patching import download_and_apply_patch


def save_manifest(manifest: Manifest, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def apply_manifest(manifest: Manifest, mode: ActionMode, confirm: bool = False) -> list[str]:
    if not confirm:
        raise RuntimeError("Refusing to apply manifest without explicit confirmation.")
    completed: list[str] = []
    seen: set[tuple[str, str | None, ActionMode]] = set()
    for entry in manifest.entries:
        source = Path(entry.source_path)
        destination = Path(entry.destination_path) if entry.destination_path else None
        key = (str(source), str(destination) if destination else None, mode)
        if key in seen:
            continue
        seen.add(key)
        if entry.patch_url:
            if mode == ActionMode.DELETE:
                completed.append(f"skipped patch for delete mode: {source}")
                continue
            if not destination:
                raise RuntimeError(f"Patch action needs a destination for {source}")
            source_data = _read_entry_source(entry.source_path, entry.source_inner_path)
            patched, patch = download_and_apply_patch(source_data, entry.patch_url)
            patched_md5 = hashlib.md5(patched).hexdigest()
            if entry.patch_expected_md5 and patched_md5.lower() != entry.patch_expected_md5.lower():
                raise RuntimeError(
                    f"Patched ROM hash mismatch for {source}: expected {entry.patch_expected_md5}, got {patched_md5}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(patched)
            completed.append(f"patched {source} with {patch.name} -> {destination}")
            continue
        if mode == ActionMode.COPY:
            if not destination:
                raise RuntimeError(f"Copy action needs a destination for {source}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            completed.append(f"copied {source} -> {destination}")
        elif mode == ActionMode.MOVE:
            if not destination:
                raise RuntimeError(f"Move action needs a destination for {source}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            completed.append(f"moved {source} -> {destination}")
        elif mode == ActionMode.DELETE:
            source.unlink()
            completed.append(f"deleted {source}")
    return completed


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
        raise ValueError(f"Unsupported report format: {fmt}")
    return path
