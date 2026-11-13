from __future__ import annotations

import os
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import py7zr
from py7zr.io import BytesIOFactory

from .chd import chd_track_sha1s
from .dat import DatIndex
from .disc import DISC_RA_MODES, disc_ra_md5
from .hashing import HEADER_HASH_MODES, arcade_ra_md5, hash_bytes, hash_stream
from .metadata import parse_no_intro_name
from .models import Platform, RomHash, ScannedRom, ScanResult
from .platforms import platform_spec
from .scan_cache import ScanHashCache

ProgressCallback = Callable[[dict[str, object]], None]
CancelCheck = Callable[[], bool]

# Contenedores admitidos para cualquier plataforma, aunque el spec no los liste.
CONTAINER_SUFFIXES = {".zip", ".7z"}

# Por encima de este tamaño, los archivos sin modo de cabecera (discos, CHDs...)
# se hashean en streaming en vez de cargarse enteros en memoria. Los modos con
# cabecera (nes/snes/n64/nds...) necesitan los datos completos, pero son pequeños.
STREAM_THRESHOLD_BYTES = 64 * 1024 * 1024

# Tamaño máximo declarado de una entrada 7z que se extrae a memoria.
MAX_7Z_ENTRY_BYTES = 4 * 1024 * 1024 * 1024

# Presupuesto de memoria por tanda de extracción 7z. El límite por entrada no
# acota el total, y py7zr no sabe leer en streaming: hay que trocear.
MAX_7Z_BATCH_BYTES = 512 * 1024 * 1024


def _should_stream(platform: Platform, size: int) -> bool:
    return platform_spec(platform).hash_mode not in HEADER_HASH_MODES and size >= STREAM_THRESHOLD_BYTES


# Imágenes de disco que se sostienen solas dentro de un contenedor. Un .cue o
# un .gdi solo describen el layout y apuntan a archivos hermanos, que al estar
# comprimidos no existen como rutas: de esos no se puede sacar el hash.
CONTAINED_DISC_SUFFIXES = {".iso", ".bin", ".chd"}


def _dump_bytes(data: bytes, destination: Path) -> None:
    destination.write_bytes(data)


def _dump_zip_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo, destination: Path) -> None:
    with archive.open(info) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target)


def _dump_7z_entry(path: Path, inner: str, size: int, destination: Path) -> None:
    destination.write_bytes(_read_single_7z_entry(path, inner, size))


def _contained_disc_ra_md5(platform: Platform, filename: str, dump: Callable[[Path], None]) -> str | None:
    """Hash RA de una imagen de disco que viene dentro de un ZIP o un 7z.

    El hash de RetroAchievements de un disco se calcula leyendo sectores
    concretos (SYSTEM.CNF, el ejecutable, la cabecera), así que necesita acceso
    aleatorio a un archivo: la entrada se vuelca a un temporal del sistema, se
    lee y se borra. Sin esto, cualquier imagen de disco comprimida se quedaba
    sin hash RA y se marcaba como incompatible con logros aunque no lo fuera.
    """
    mode = platform_spec(platform).hash_mode
    if mode not in DISC_RA_MODES or Path(filename).suffix.lower() not in CONTAINED_DISC_SUFFIXES:
        return None
    handle, name = tempfile.mkstemp(suffix=Path(filename).suffix)
    os.close(handle)
    temporal = Path(name)
    try:
        dump(temporal)
        return disc_ra_md5(temporal, mode)
    except OSError:
        return None
    finally:
        temporal.unlink(missing_ok=True)


def _read_7z_entries(archive: py7zr.SevenZipFile, targets: list[str], largest: int) -> dict:
    """Extrae entradas de un 7z a memoria (el formato no permite lectura aleatoria en streaming)."""
    factory = BytesIOFactory(limit=max(largest, 1))
    archive.extract(targets=targets, factory=factory)
    return factory.products


def _read_single_7z_entry(path: Path, inner: str, size: int) -> bytes:
    with py7zr.SevenZipFile(path) as archive:
        products = _read_7z_entries(archive, [inner], size)
    buffer = products.get(inner)
    return buffer.read() if buffer is not None else b""


def _scan_payload(
    *,
    source_path: Path,
    container_path: Path,
    inner_path: str | None,
    platform: Platform,
    dat_index: DatIndex | None,
    data: bytes | None = None,
    hashes: RomHash | None = None,
    data_loader: Callable[[], bytes] | None = None,
) -> ScannedRom:
    if hashes is None:
        hashes = hash_bytes(data or b"", platform)
    display_filename = inner_path or source_path.name
    if dat_index is None:
        dat_game = None
    elif data is not None:
        dat_game = dat_index.match_data(data, hashes, filename=display_filename)
    else:
        dat_game = dat_index.match_any(hashes)
        if dat_game is None and data_loader is not None and dat_index.has_header_candidates:
            dat_game = dat_index.match_data(data_loader(), hashes, filename=display_filename)
    display_name = dat_game.roms[0].name if dat_game and dat_game.roms else display_filename
    metadata = parse_no_intro_name(display_name)
    return ScannedRom(
        id=str(uuid.uuid4()),
        source_path=str(source_path),
        container_path=str(container_path),
        inner_path=inner_path,
        platform=platform,
        hashes=hashes,
        dat_game=dat_game,
        metadata=metadata,
    )


def _hash_file(path: Path, platform: Platform) -> RomHash:
    if _should_stream(platform, path.stat().st_size):
        with path.open("rb") as fh:
            return hash_stream(fh)
    return hash_bytes(path.read_bytes(), platform)


def _scan_arcade_container(
    *,
    path: Path,
    platform: Platform,
    dat_index: DatIndex | None,
    cache: ScanHashCache | None,
) -> ScannedRom:
    stat = path.stat()
    hashes = cache.get(str(path), None, platform, stat.st_size, stat.st_mtime_ns) if cache else None
    if hashes is None:
        hashes = _hash_file(path, platform)
        if cache:
            cache.put(str(path), None, platform, stat.st_size, stat.st_mtime_ns, hashes)
    set_name = path.parent.name if path.suffix.lower() == ".chd" else path.stem
    hashes.ra_md5 = arcade_ra_md5(set_name)
    dat_game = dat_index.match_set(set_name) if dat_index else None
    display_name = (dat_game.description or dat_game.name) if dat_game else path.name
    metadata = parse_no_intro_name(display_name)
    return ScannedRom(
        id=str(uuid.uuid4()),
        source_path=str(path),
        container_path=str(path),
        inner_path=None,
        platform=platform,
        hashes=hashes,
        dat_game=dat_game,
        metadata=metadata,
    )


def _scan_loose_file(path: Path, platform: Platform, dat_index: DatIndex | None, cache: ScanHashCache | None) -> ScannedRom:
    stat = path.stat()
    hash_mode = platform_spec(platform).hash_mode
    is_chd = path.suffix.lower() == ".chd"
    cached = cache.get(str(path), None, platform, stat.st_size, stat.st_mtime_ns) if cache else None
    if cached is not None:
        if cached.ra_md5 is None:
            cached.ra_md5 = disc_ra_md5(path, hash_mode)
        if is_chd and cached.track_sha1s is None:
            # entrada cacheada antes del soporte CHD: completar y re-guardar,
            # que calcular los sha1 de pista descomprime el CHD entero
            cached.track_sha1s = chd_track_sha1s(path)
            if cache and cached.track_sha1s is not None:
                cache.put(str(path), None, platform, stat.st_size, stat.st_mtime_ns, cached)
        return _scan_payload(hashes=cached, data_loader=path.read_bytes, source_path=path, container_path=path, inner_path=None, platform=platform, dat_index=dat_index)
    if _should_stream(platform, stat.st_size):
        with path.open("rb") as fh:
            hashes = hash_stream(fh)
    else:
        data = path.read_bytes()
        hashes = hash_bytes(data, platform)
    if hashes.ra_md5 is None:
        hashes.ra_md5 = disc_ra_md5(path, hash_mode)
    if is_chd:
        hashes.track_sha1s = chd_track_sha1s(path)
    if cache:
        cache.put(str(path), None, platform, stat.st_size, stat.st_mtime_ns, hashes)
    if _should_stream(platform, stat.st_size):
        return _scan_payload(hashes=hashes, source_path=path, container_path=path, inner_path=None, platform=platform, dat_index=dat_index)
    return _scan_payload(data=data, hashes=hashes, source_path=path, container_path=path, inner_path=None, platform=platform, dat_index=dat_index)


def _scan_zip(path: Path, platform: Platform, rom_extensions: set[str], dat_index: DatIndex | None, cache: ScanHashCache | None) -> list[ScannedRom] | None:
    """Devuelve las ROMs del ZIP, o None si no contiene ninguna entrada soportada."""
    stat = path.stat()
    roms: list[ScannedRom] = []
    with zipfile.ZipFile(path) as archive:
        rom_entries = [info for info in archive.infolist() if not info.is_dir() and Path(info.filename).suffix.lower() in rom_extensions]
        if not rom_entries:
            return None
        for info in rom_entries:
            cached = cache.get(str(path), info.filename, platform, info.file_size, stat.st_mtime_ns) if cache else None
            if cached is not None:
                if cached.ra_md5 is None:
                    cached.ra_md5 = _contained_disc_ra_md5(platform, info.filename, partial(_dump_zip_entry, archive, info))
                    if cache and cached.ra_md5 is not None:
                        cache.put(str(path), info.filename, platform, info.file_size, stat.st_mtime_ns, cached)
                rom = _scan_payload(
                    hashes=cached,
                    data_loader=partial(archive.read, info),
                    source_path=path,
                    container_path=path,
                    inner_path=info.filename,
                    platform=platform,
                    dat_index=dat_index,
                )
            elif _should_stream(platform, info.file_size):
                with archive.open(info) as fh:
                    hashes = hash_stream(fh)
                if hashes.ra_md5 is None:
                    hashes.ra_md5 = _contained_disc_ra_md5(platform, info.filename, partial(_dump_zip_entry, archive, info))
                if cache:
                    cache.put(str(path), info.filename, platform, info.file_size, stat.st_mtime_ns, hashes)
                rom = _scan_payload(hashes=hashes, source_path=path, container_path=path, inner_path=info.filename, platform=platform, dat_index=dat_index)
            else:
                data = archive.read(info)
                hashes = hash_bytes(data, platform)
                if hashes.ra_md5 is None:
                    hashes.ra_md5 = _contained_disc_ra_md5(platform, info.filename, partial(_dump_bytes, data))
                if cache:
                    cache.put(str(path), info.filename, platform, info.file_size, stat.st_mtime_ns, hashes)
                rom = _scan_payload(data=data, hashes=hashes, source_path=path, container_path=path, inner_path=info.filename, platform=platform, dat_index=dat_index)
            roms.append(rom)
    return roms


def _scan_7z(path: Path, platform: Platform, rom_extensions: set[str], dat_index: DatIndex | None, cache: ScanHashCache | None) -> tuple[list[ScannedRom], list[str]] | None:
    """Devuelve (ROMs, entradas omitidas) del 7z, o None si no contiene ninguna entrada soportada."""
    stat = path.stat()
    roms: list[ScannedRom] = []
    skipped: list[str] = []
    with py7zr.SevenZipFile(path) as archive:
        all_entries = [info for info in archive.list() if not info.is_directory and Path(info.filename).suffix.lower() in rom_extensions]
        if not all_entries:
            return None
        # La extracción 7z es en memoria: un tamaño declarado desmesurado
        # (archivo-bomba o imagen gigante) se omite en vez de agotar la RAM.
        entries = []
        for info in all_entries:
            if info.uncompressed > MAX_7Z_ENTRY_BYTES:
                skipped.append(f"{path} / {info.filename} (entrada de {info.uncompressed / (1024**3):.1f} GiB supera el límite de extracción 7z)")
            else:
                entries.append(info)
        if not entries:
            return roms, skipped
        pending = []
        por_entrada: dict[str, ScannedRom] = {}
        for info in entries:
            cached = cache.get(str(path), info.filename, platform, info.uncompressed, stat.st_mtime_ns) if cache else None
            if cached is None:
                pending.append(info)
                continue
            if cached.ra_md5 is None:
                cached.ra_md5 = _contained_disc_ra_md5(platform, info.filename, partial(_dump_7z_entry, path, info.filename, info.uncompressed))
                if cache and cached.ra_md5 is not None:
                    cache.put(str(path), info.filename, platform, info.uncompressed, stat.st_mtime_ns, cached)
            por_entrada[info.filename] = _scan_payload(
                hashes=cached,
                data_loader=partial(_read_single_7z_entry, path, info.filename, info.uncompressed),
                source_path=path,
                container_path=path,
                inner_path=info.filename,
                platform=platform,
                dat_index=dat_index,
            )
        # Por tandas: el límite por entrada no acota el total, así que un 7z con
        # dos mil entradas de 2 MB se traía 4 GB a memoria de una vez.
        for index, batch in enumerate(_7z_batches(pending, MAX_7Z_BATCH_BYTES)):
            if index:
                archive.reset()  # py7zr no permite dos extracciones sin rebobinar
            data_map = _read_7z_entries(archive, [item.filename for item in batch], max(item.uncompressed for item in batch))
            for info in batch:
                buffer = data_map.get(info.filename)
                if buffer is None:
                    continue
                data = buffer.read()
                hashes = hash_bytes(data, platform)
                if hashes.ra_md5 is None:
                    hashes.ra_md5 = _contained_disc_ra_md5(platform, info.filename, partial(_dump_bytes, data))
                if cache:
                    cache.put(str(path), info.filename, platform, info.uncompressed, stat.st_mtime_ns, hashes)
                por_entrada[info.filename] = _scan_payload(
                    data=data, hashes=hashes, source_path=path, container_path=path, inner_path=info.filename, platform=platform, dat_index=dat_index
                )
            data_map.clear()
    # En el orden del archivo, que es el que ve quien mira el resultado.
    roms.extend(por_entrada[info.filename] for info in entries if info.filename in por_entrada)
    return roms, skipped


def _7z_batches(entries: list, limit: int) -> Iterator[list]:
    """Agrupa entradas para no pasar de `limit` bytes descomprimidos por tanda.

    Una entrada que por sí sola pase del límite va en su propia tanda: ya la
    acota MAX_7Z_ENTRY_BYTES, y partirla no se puede.
    """
    batch: list = []
    total = 0
    for info in entries:
        if batch and total + info.uncompressed > limit:
            yield batch
            batch, total = [], 0
        batch.append(info)
        total += info.uncompressed
    if batch:
        yield batch


def _scan_one_path(
    path: Path,
    platform: Platform,
    *,
    arcade_mode: bool,
    rom_extensions: set[str],
    dat_index: DatIndex | None,
    cache: ScanHashCache | None,
) -> tuple[list[ScannedRom], list[str]]:
    """Escanea una ruta y devuelve (roms, archivos no procesados)."""
    try:
        if arcade_mode:
            return [_scan_arcade_container(path=path, platform=platform, dat_index=dat_index, cache=cache)], []
        suffix = path.suffix.lower()
        if suffix in rom_extensions:
            return [_scan_loose_file(path, platform, dat_index, cache)], []
        if suffix == ".zip":
            roms = _scan_zip(path, platform, rom_extensions, dat_index, cache)
            return (roms, []) if roms is not None else ([], [str(path)])
        if suffix == ".7z":
            outcome = _scan_7z(path, platform, rom_extensions, dat_index, cache)
            return outcome if outcome is not None else ([], [str(path)])
        return [], [str(path)]
    except (OSError, zipfile.BadZipFile, py7zr.Bad7zFile):
        return [], [str(path)]


def scan_file(path: Path, platform: Platform, dat_index: DatIndex | None = None) -> list[ScannedRom]:
    """Escanea un único archivo (suelto o contenedor). Lo usa el verificador de descargas."""
    spec = platform_spec(platform)
    roms, _unmatched = _scan_one_path(
        path,
        platform,
        arcade_mode=spec.kind == "arcade",
        rom_extensions=set(spec.rom_extensions),
        dat_index=dat_index,
        cache=None,
    )
    return roms


def scan_directory(
    input_path: Path,
    platform: Platform,
    dat_index: DatIndex | None = None,
    dat_path: Path | None = None,
    progress: ProgressCallback | None = None,
    hash_cache: Path | None = None,
    workers: int | None = None,
    cancelled: CancelCheck | None = None,
) -> ScanResult:
    """Escanea una carpeta y devuelve lo identificado.

    `cancelled` se consulta entre archivos: un escaneo de cientos de GB tenía
    que terminar o cerrarse la aplicación entera. Lo ya escaneado se devuelve
    igual, y la fase del progreso acaba en "cancelled" para que quien llame
    sepa que la lista está incompleta.
    """
    result = ScanResult(id=str(uuid.uuid4()), platform=platform, input_path=str(input_path), dat_path=str(dat_path) if dat_path else None)
    spec = platform_spec(platform)
    supported_extensions = set(spec.extensions)
    supported_rom_extensions = set(spec.rom_extensions)
    arcade_mode = spec.kind == "arcade"
    all_paths = [input_path] if input_path.is_file() else sorted(input_path.rglob("*"))
    paths = [path for path in all_paths if path.is_file() and (path.suffix.lower() in supported_extensions or path.suffix.lower() in CONTAINER_SUFFIXES)]
    total = len(paths)
    cache = ScanHashCache(hash_cache) if hash_cache else None
    if workers is None:
        workers = min(8, os.cpu_count() or 1)
    if progress:
        progress({"phase": "start", "current": 0, "total": total, "path": "", "roms": 0, "matched": 0})

    def scan_one(path: Path) -> tuple[list[ScannedRom], list[str]]:
        return _scan_one_path(
            path,
            platform,
            arcade_mode=arcade_mode,
            rom_extensions=supported_rom_extensions,
            dat_index=dat_index,
            cache=cache,
        )

    def results_in_order() -> Iterator[tuple[Path, tuple[list[ScannedRom], list[str]]]]:
        # hashlib y zlib liberan el GIL, así que los hilos hashean en paralelo de verdad.
        if workers > 1 and len(paths) > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(scan_one, path) for path in paths]
                try:
                    for path, future in zip(paths, futures, strict=True):
                        if cancelled and cancelled():
                            return
                        yield path, future.result()
                finally:
                    # Las que aún no han empezado se descartan; las que están a
                    # medio hashear terminan solas al cerrar el pool.
                    for pending in futures:
                        pending.cancel()
        else:
            for path in paths:
                if cancelled and cancelled():
                    return
                yield path, scan_one(path)

    try:
        for index, (path, (roms, unmatched)) in enumerate(results_in_order(), start=1):
            result.roms.extend(roms)
            result.unmatched_files.extend(unmatched)
            if progress:
                progress(
                    {
                        "phase": "scan",
                        "current": index,
                        "total": total,
                        "path": str(path),
                        "roms": len(result.roms),
                        "matched": sum(1 for rom in result.roms if rom.dat_game is not None),
                    }
                )
    finally:
        if cache:
            cache.close()

    if progress:
        progress(
            {
                "phase": "cancelled" if cancelled and cancelled() else "done",
                "current": total,
                "total": total,
                "path": "",
                "roms": len(result.roms),
                "matched": sum(1 for rom in result.roms if rom.dat_game is not None),
            }
        )
    return result
