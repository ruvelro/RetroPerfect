from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import shutil
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .models import ARCHIVE_MODES, ActionMode, ContainerMode, Manifest, ManifestArchive
from .patching import download_and_apply_patch
from .paths import project_state_dir
from .torrentzip import write_torrentzip


def save_manifest(manifest: Manifest, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


HASH_CHUNK_SIZE = 1024 * 1024

ProgressCallback = Callable[[dict[str, object]], None]
CancelCheck = Callable[[], bool]

# Prefijo del aviso de destino ocupado: `blocking_issues` filtra por él cuando
# el usuario autoriza reemplazar, así que el mensaje y el filtro tienen que
# salir del mismo sitio para no divergir.
OCCUPIED_DESTINATION_PREFIX = "El destino ya existe"


def preflight_manifest(manifest: Manifest) -> list[str]:
    """Comprueba orígenes, colisiones de destino y espacio en disco antes de aplicar."""
    issues: list[str] = []
    destinations: dict[str, str] = {}
    needed_by_device: dict[int, int] = {}
    device_roots: dict[int, Path] = {}
    for entry in manifest.entries:
        source = Path(entry.source_path)
        if not source.exists():
            if not _already_done_without_source(entry):
                issues.append(f"Origen no encontrado: {source}")
            continue
        if not entry.destination_path:
            continue
        previous = destinations.get(entry.destination_path)
        # Con rezip, varias entradas comparten destino a propósito: todas van al
        # mismo ZIP del juego. Ahí la colisión no existe.
        if previous is not None and previous != entry.source_path and entry.container_mode not in ARCHIVE_MODES:
            issues.append(f"Colisión de destino: {entry.destination_path} recibiría {previous} y también {entry.source_path}")
        destinations[entry.destination_path] = entry.source_path
        destination = Path(entry.destination_path)
        # Un destino ocupado por otro archivo se avisa antes de escribir: la
        # copia lo pisaba en silencio y con enlaces duros reventaba a medias.
        # El del mismo tamaño se da por ya aplicado y lo confirma el MD5 al
        # aplicar, así que repetir un plan ya aplicado no cuesta espacio.
        already_applied = False
        if destination.exists():
            # Con un contenedor, el tamaño que se escribe es el de la ROM (o el
            # del ZIP nuevo), no el del archivo de origen.
            esperado = entry.source_size if entry.container_mode == ContainerMode.EXTRACT and entry.source_size else source.stat().st_size
            if entry.patch_url or entry.container_mode in ARCHIVE_MODES or destination.stat().st_size == esperado:
                already_applied = True
            else:
                issues.append(
                    f"{OCCUPIED_DESTINATION_PREFIX} y no es el mismo archivo: {destination}. Muévelo de ahí o aplica con --overwrite para reemplazarlo."
                )
        root = _existing_ancestor(destination)
        device = os.stat(root).st_dev
        cross_device_move = entry.action == ActionMode.MOVE and os.stat(source).st_dev != device
        if not already_applied and (bool(entry.patch_url) or entry.action == ActionMode.COPY or cross_device_move):
            needed_by_device[device] = needed_by_device.get(device, 0) + bytes_to_write(entry, source)
            device_roots.setdefault(device, root)
    for device, needed in needed_by_device.items():
        root = device_roots[device]
        free = shutil.disk_usage(root).free
        if needed > free:
            issues.append(f"Espacio insuficiente en {root}: se necesitan {_human_size(needed)} y quedan {_human_size(free)} libres.")
    return issues


def bytes_to_write(entry, source: Path) -> int:
    """Cuánto se va a escribir en el destino por esta entrada.

    Copiar un contenedor escribe el contenedor, pero extraer escribe solo la ROM
    y reempaquetar escribe un ZIP que como mucho ocupa lo que ocupan sus
    archivos sin comprimir: dar por bueno el tamaño del origen bloquearía un
    plan que sí cabe (un ZIP de 4 GB del que se saca una ROM de 2 MB).
    """
    if entry.container_mode != ContainerMode.KEEP and entry.source_size:
        return int(entry.source_size)
    return source.stat().st_size


def _already_done_without_source(entry) -> bool:
    """La operación ya se hizo, y por eso su origen no está.

    Permite retomar una aplicación interrumpida: en cuanto un `move` o un
    borrado se completaba, el preflight cortaba con "Origen no encontrado" y el
    plan entero quedaba bloqueado, sin forma de seguir con lo que faltaba.
    """
    if entry.action == ActionMode.DELETE:
        return True  # lo que había que borrar ya no está: el estado final es el pedido
    return bool(entry.destination_path) and Path(entry.destination_path).exists()


def blocking_issues(manifest: Manifest, overwrite: bool = False) -> list[str]:
    """Problemas del preflight que impiden aplicar, según si se permite reemplazar.

    Un destino ocupado deja de ser bloqueante cuando el usuario ya ha dicho que
    quiere reemplazarlo; el resto (orígenes que faltan, colisiones, espacio) lo
    es siempre.
    """
    return [issue for issue in preflight_manifest(manifest) if not (overwrite and issue.startswith(OCCUPIED_DESTINATION_PREFIX))]


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
    journal_dir: Path | None = None,
    link: bool = False,
    overwrite: bool = False,
    progress: ProgressCallback | None = None,
    cancelled: CancelCheck | None = None,
) -> list[str]:
    """Aplica el manifiesto y devuelve el registro de lo hecho.

    `progress` recibe una actualización por operación: copiar una colección de
    cientos de GB no puede ser una barra que no se mueve. `cancelled` se
    consulta entre operaciones, nunca a mitad de un archivo, así que no deja
    copias a medias; lo aplicado hasta ahí queda en el journal.
    """
    if not confirm:
        raise RuntimeError("No se aplica el manifiesto sin confirmación explícita.")
    issues = blocking_issues(manifest, overwrite)
    if issues:
        raise RuntimeError("No se puede aplicar el manifiesto:\n- " + "\n- ".join(issues))
    completed: list[str] = []
    reverts: list[dict[str, str]] = []
    try:
        _apply_entries(manifest, mode, verify, hard_delete, trash_dir, completed, link=link, overwrite=overwrite, progress=progress, cancelled=cancelled, reverts=reverts)
        if not (cancelled and cancelled()):
            _write_archives(manifest, completed, reverts, verify, overwrite)
            # Un .m3u que liste discos que no se han copiado es peor que no tenerlo.
            _write_playlists(manifest, completed, reverts)
        if progress:
            hechas = len(manifest.entries)
            progress({"phase": "cancelled" if cancelled and cancelled() else "done", "current": hechas, "total": hechas, "path": "", "action": ""})
    except Exception as exc:
        _write_journal(manifest, completed, verify, hard_delete, journal_dir, error=str(exc), reverts=reverts)
        raise
    _write_journal(manifest, completed, verify, hard_delete, journal_dir, reverts=reverts)
    return completed


def _write_journal(
    manifest: Manifest,
    completed: list[str],
    verify: bool,
    hard_delete: bool,
    journal_dir: Path | None,
    error: str | None = None,
    reverts: list[dict[str, str]] | None = None,
) -> None:
    """Deja constancia de las operaciones aplicadas (y del error, si lo hubo).

    `operations` es el texto que lee una persona; `reverts` es lo mismo en
    campos, que es lo que necesita `undo`: deshacer leyendo la prosa sería el
    mismo acoplamiento frágil que tener la interfaz adivinando iconos a partir
    de los motivos.
    """
    if not completed and error is None:
        return
    root = journal_dir or (project_state_dir() / "applied")
    root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "manifest_id": manifest.id,
        "platform": manifest.platform.value,
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "verify": verify,
        "hard_delete": hard_delete,
        "operations": completed,
        "reverts": reverts or [],
    }
    if error is not None:
        payload["error"] = error
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")  # hora local: es un nombre que lee el usuario
    (root / f"{stamp}-{manifest.id}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _can_hardlink(source: Path, destination: Path) -> bool:
    """Un enlace duro solo existe dentro del mismo sistema de archivos."""
    try:
        return os.stat(source).st_dev == os.stat(destination.parent).st_dev
    except OSError:
        return False


def _write_playlists(manifest: Manifest, completed: list[str], reverts: list[dict[str, str]] | None = None) -> None:
    """Escribe los .m3u de los juegos de varios discos.

    El emulador guarda la partida contra el nombre del .m3u, así que sin él
    cada disco tiene su propio save y el juego no se puede terminar.
    """
    for playlist in manifest.playlists:
        path = Path(playlist.path)
        if not playlist.entries:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(playlist.entries) + "\n", encoding="utf-8")
        if reverts is not None:
            reverts.append({"action": "create", "destination": str(path)})
        completed.append(f"playlist {path} ({len(playlist.entries)} discos)")


def _write_archives(manifest: Manifest, completed: list[str], reverts: list[dict[str, str]] | None, verify: bool, overwrite: bool = False) -> None:
    """Escribe un ZIP por juego con solo los archivos que el plan conserva.

    Es lo que faltaba para curar de verdad una colección en contenedores: antes
    un ZIP con el juego elegido y dos descartes viajaba entero, y no había forma
    de reempaquetar. Cada miembro se verifica por MD5 **antes** de entrar, así
    que un contenedor que cambió desde el escaneo para el plan en vez de colarse
    dentro del ZIP nuevo.

    Los nombres de dentro son los del DAT cuando se conocen: es lo que hace que
    dos colecciones curadas con el mismo DAT salgan iguales.
    """
    for archive in manifest.archives:
        destino = Path(archive.path)
        if not archive.members:
            continue
        if destino.exists() and _settle_existing_archive(destino, archive, overwrite, completed):
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_suffix(destino.suffix + ".part")
        try:
            contenidos: list[tuple[str, bytes]] = []
            for member in archive.members:
                datos = _read_entry_source(member.source_path, member.source_inner_path)
                real = hashlib.md5(datos).hexdigest()
                if member.md5 and real != member.md5.lower():
                    raise RuntimeError(
                        f"{member.name} cambió desde el escaneo (MD5 esperado {member.md5}, actual {real}): no entra en {destino.name}. Reescanea y regenera el plan."
                    )
                contenidos.append((member.name, datos))
            if archive.mode == ContainerMode.TORRENTZIP:
                write_torrentzip(parcial, contenidos)
            else:
                with zipfile.ZipFile(parcial, "w", zipfile.ZIP_DEFLATED) as nuevo:
                    for nombre, datos in contenidos:
                        nuevo.writestr(nombre, datos)
        except Exception:
            parcial.unlink(missing_ok=True)
            raise
        parcial.replace(destino)
        if verify:
            _verify_archive(destino, archive)
        if reverts is not None:
            reverts.append({"action": "create", "destination": str(destino), "md5": _file_md5(destino)})
        canonico = " canónico (TorrentZip)" if archive.mode == ContainerMode.TORRENTZIP else ""
        completed.append(f"empaquetado{canonico} {destino} con {len(archive.members)} archivo(s)" + (" (contenido verificado)" if verify else ""))


def _settle_existing_archive(destino: Path, archive: ManifestArchive, overwrite: bool, completed: list[str]) -> bool:
    """Resuelve un ZIP de destino que ya existe. True si no hay que tocarlo.

    Misma regla que con los archivos sueltos: si ya contiene exactamente lo
    planificado se omite —repetir un plan no rehace los ZIP— y si no, se para
    antes de escribir. `--overwrite` lo reemplaza.
    """
    try:
        _verify_archive(destino, archive)
    except (RuntimeError, OSError, zipfile.BadZipFile):
        if not overwrite:
            raise RuntimeError(
                f"{OCCUPIED_DESTINATION_PREFIX} y no contiene lo planificado: {destino}. "
                "Muévelo de ahí o vuelve a aplicar con --overwrite para reemplazarlo."
            ) from None
        return False
    completed.append(f"omitido {destino}: ya contenía los {len(archive.members)} archivo(s) planificados")
    return True


def _verify_archive(destino: Path, archive: ManifestArchive) -> None:
    """Comprueba que el ZIP escrito contiene exactamente lo planificado.

    Verificar el ZIP por su propio MD5 no diría nada: lo que importa es que
    dentro esté cada archivo con su contenido.
    """
    esperados = {member.name: member.md5.lower() for member in archive.members}
    with zipfile.ZipFile(destino) as leido:
        presentes = {info.filename for info in leido.infolist() if not info.is_dir()}
        if presentes != set(esperados):
            raise RuntimeError(f"El ZIP {destino} no contiene lo planificado: {sorted(presentes)} frente a {sorted(esperados)}")
        for nombre, md5 in esperados.items():
            if md5 and hashlib.md5(leido.read(nombre)).hexdigest() != md5:
                raise RuntimeError(f"{nombre} dentro de {destino} no coincide con lo planificado.")


def _apply_entries(
    manifest: Manifest,
    mode: ActionMode | None,
    verify: bool,
    hard_delete: bool,
    trash_dir: Path | None,
    completed: list[str],
    link: bool = False,
    overwrite: bool = False,
    progress: ProgressCallback | None = None,
    cancelled: CancelCheck | None = None,
    reverts: list[dict[str, str]] | None = None,
) -> None:
    anotar = reverts if reverts is not None else []
    session_trash: Path | None = None
    trashed: list[dict[str, str]] = []
    seen: set[tuple[str, str | None, ActionMode]] = set()
    total = len(manifest.entries)
    try:
        for index, entry in enumerate(manifest.entries, start=1):
            if cancelled and cancelled():
                completed.append(f"cancelado por el usuario tras {index - 1} de {total} operaciones")
                break
            if progress:
                progress({"phase": "apply", "current": index, "total": total, "path": entry.destination_path or entry.source_path, "action": entry.action.value})
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
            if not source.exists() and _already_done_without_source(entry):
                completed.append(f"omitido {source}: la operación ya estaba hecha")
                continue
            if (
                destination is not None
                and action != ActionMode.DELETE
                and entry.container_mode not in ARCHIVE_MODES
                and destination.exists()
                and _settle_existing_destination(entry, source, destination, overwrite, completed)
            ):
                continue
            if entry.container_mode in ARCHIVE_MODES:
                # El ZIP lo escribe `_write_archives`, que junta todos los
                # archivos del juego: aquí no hay una operación por archivo.
                continue
            if entry.container_mode == ContainerMode.EXTRACT and entry.source_inner_path and action != ActionMode.DELETE:
                if not destination:
                    raise RuntimeError(f"Extraer necesita un destino para {source}")
                datos = _read_entry_source(entry.source_path, entry.source_inner_path)
                extraido_md5 = hashlib.md5(datos).hexdigest()
                if entry.source_md5 and extraido_md5 != entry.source_md5.lower():
                    raise RuntimeError(f"El contenido de {entry.source_inner_path} en {source} cambió desde el escaneo. Reescanea y regenera el plan.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(datos)
                anotar.append({"action": "create", "destination": str(destination), "md5": extraido_md5})
                if verify:
                    _verify_destination(destination, extraido_md5, source)
                    completed.append(f"extraído {entry.source_inner_path} de {source} -> {destination} (md5 verificado)")
                else:
                    completed.append(f"extraído {entry.source_inner_path} de {source} -> {destination}")
                continue
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
                anotar.append({"action": "create", "destination": str(destination), "md5": patched_md5})
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
                if link and _can_hardlink(source, destination):
                    # El enlace duro comparte inodo: no hay copia que verificar,
                    # pero sí se comprueba que el origen no cambió desde el escaneo.
                    if verify:
                        _check_source_md5(entry, _file_md5(source))
                    os.link(source, destination)
                    anotar.append({"action": "create", "destination": str(destination)})
                    completed.append(f"enlazado {source} -> {destination} (enlace duro, sin ocupar espacio)")
                elif verify:
                    source_md5 = _copy_hashing(source, destination)
                    _check_source_md5(entry, source_md5)
                    _verify_destination(destination, source_md5, source)
                    anotar.append({"action": "create", "destination": str(destination), "md5": source_md5})
                    completed.append(f"copiado {source} -> {destination} (md5 verificado)")
                else:
                    shutil.copy2(source, destination)
                    anotar.append({"action": "create", "destination": str(destination)})
                    completed.append(f"copiado {source} -> {destination}")
            elif action == ActionMode.MOVE:
                if not destination:
                    raise RuntimeError(f"La acción de mover necesita un destino para {source}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                move_md5 = _file_md5(source) if verify else None
                if move_md5 is not None:
                    _check_source_md5(entry, move_md5)
                shutil.move(str(source), str(destination))
                anotar.append({"action": "move", "source": str(source), "destination": str(destination), **({"md5": move_md5} if move_md5 else {})})
                if move_md5 is not None:
                    _verify_destination(destination, move_md5, source)
                    completed.append(f"movido {source} -> {destination} (md5 verificado)")
                else:
                    completed.append(f"movido {source} -> {destination}")
            elif action == ActionMode.DELETE:
                if hard_delete:
                    source.unlink()
                    # Se anota aunque no se pueda deshacer: `undo` tiene que
                    # poder decir cuántos archivos no va a recuperar.
                    anotar.append({"action": "hard_delete", "source": str(source)})
                    completed.append(f"borrado definitivo {source}")
                else:
                    if session_trash is None:
                        root = trash_dir or (project_state_dir() / "trash")
                        session_trash = root / datetime.now().strftime("%Y%m%d-%H%M%S")  # hora local: se teclea en trash-restore
                        session_trash.mkdir(parents=True, exist_ok=True)
                    target = _trash_target(session_trash, source.name)
                    shutil.move(str(source), str(target))
                    trashed.append({"original": str(source), "trashed": target.name})
                    anotar.append({"action": "trash", "original": str(source), "trashed": str(target)})
                    completed.append(f"movido a papelera {source} -> {target}")
    finally:
        if session_trash is not None and trashed:
            (session_trash / "index.json").write_text(
                json.dumps({"created": datetime.now().astimezone().isoformat(timespec="seconds"), "files": trashed}, indent=2),
                encoding="utf-8",
            )


def _settle_existing_destination(entry, source: Path, destination: Path, overwrite: bool, completed: list[str]) -> bool:
    """Resuelve un destino ya ocupado. Devuelve True si no hay que tocarlo.

    Aplicar dos veces el mismo plan no debe duplicar trabajo ni, mucho peor,
    sobrescribir un archivo distinto que el usuario tenía ahí: si el contenido
    ya es el que toca se omite la operación, y si no, se para antes de escribir
    nada. Con `overwrite` se borra primero, que es lo que además necesita el
    enlace duro (`os.link` no sobrescribe: falla).
    """
    if entry.patch_url:
        expected = entry.patch_expected_md5
    elif entry.container_mode == ContainerMode.EXTRACT:
        # Lo que se escribió es la ROM de dentro, no el contenedor: comparar con
        # el MD5 del ZIP nunca casaría y una extracción ya hecha se tomaría por
        # un archivo ajeno.
        expected = entry.source_md5
    else:
        expected = _file_md5(source)
    actual = _file_md5(destination)
    if expected and actual.lower() == expected.lower():
        origen = f" (el origen {source} se deja intacto)" if entry.action == ActionMode.MOVE else ""
        completed.append(f"omitido {destination}: ya estaba aplicado, mismo MD5{origen}")
        return True
    if not overwrite:
        raise RuntimeError(
            f"El destino {destination} ya existe con otro contenido (MD5 {actual}). "
            "Muévelo de ahí o vuelve a aplicar con --overwrite para reemplazarlo."
        )
    destination.unlink()
    return False


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
        if source.suffix.lower() == ".7z":
            import py7zr
            from py7zr.io import BytesIOFactory

            with py7zr.SevenZipFile(source) as sevenzip:
                sizes = [info.uncompressed for info in sevenzip.list() if info.filename == inner_path]
                if not sizes:
                    raise RuntimeError(f"No se encontró {inner_path} dentro de {source}")
                factory = BytesIOFactory(limit=max(sizes[0], 1))
                sevenzip.extract(targets=[inner_path], factory=factory)
                return factory.products[inner_path].read()
        with zipfile.ZipFile(source) as archive:
            return archive.read(inner_path)
    return source.read_bytes()


REPORT_FORMATS = ("html", "json", "csv")


def report_manifest(manifest: Manifest, path: Path, fmt: str) -> Path:
    if fmt not in REPORT_FORMATS:
        # Antes creaba el directorio de informes y fallaba después con un ValueError
        # sin capturar, dejando restos de una operación que nunca iba a terminar.
        raise ValueError(f"Formato de informe desconocido: {fmt}. Usa uno de: {', '.join(REPORT_FORMATS)}.")
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
