from __future__ import annotations

import os
import uuid
import zipfile
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import py7zr
from py7zr.io import BytesIOFactory

from .dat import DatIndex
from .hashing import hash_bytes, hash_stream
from .metadata import parse_no_intro_name
from .models import Platform, RomHash, ScannedRom, ScanResult
from .platforms import platform_spec
from .scan_cache import ScanHashCache

ProgressCallback = Callable[[dict[str, object]], None]

# Contenedores admitidos para cualquier plataforma, aunque el spec no los liste.
CONTAINER_SUFFIXES = {".zip", ".7z"}

# Above this size, hash_mode 'direct' files (discs, CHDs...) are hashed in
# streaming instead of loading the whole file in memory. Header-aware modes
# (nes/snes/n64) always need the full data, but those files are small.
STREAM_THRESHOLD_BYTES = 64 * 1024 * 1024


def _should_stream(platform: Platform, size: int) -> bool:
    return platform_spec(platform).hash_mode == "direct" and size >= STREAM_THRESHOLD_BYTES


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
    cached = cache.get(str(path), None, platform, stat.st_size, stat.st_mtime_ns) if cache else None
    if cached is not None:
        return _scan_payload(hashes=cached, data_loader=path.read_bytes, source_path=path, container_path=path, inner_path=None, platform=platform, dat_index=dat_index)
    if _should_stream(platform, stat.st_size):
        with path.open("rb") as fh:
            hashes = hash_stream(fh)
        if cache:
            cache.put(str(path), None, platform, stat.st_size, stat.st_mtime_ns, hashes)
        return _scan_payload(hashes=hashes, source_path=path, container_path=path, inner_path=None, platform=platform, dat_index=dat_index)
    data = path.read_bytes()
    hashes = hash_bytes(data, platform)
    if cache:
        cache.put(str(path), None, platform, stat.st_size, stat.st_mtime_ns, hashes)
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
                if cache:
                    cache.put(str(path), info.filename, platform, info.file_size, stat.st_mtime_ns, hashes)
                rom = _scan_payload(hashes=hashes, source_path=path, container_path=path, inner_path=info.filename, platform=platform, dat_index=dat_index)
            else:
                data = archive.read(info)
                hashes = hash_bytes(data, platform)
                if cache:
                    cache.put(str(path), info.filename, platform, info.file_size, stat.st_mtime_ns, hashes)
                rom = _scan_payload(data=data, hashes=hashes, source_path=path, container_path=path, inner_path=info.filename, platform=platform, dat_index=dat_index)
            roms.append(rom)
    return roms


def _scan_7z(path: Path, platform: Platform, rom_extensions: set[str], dat_index: DatIndex | None, cache: ScanHashCache | None) -> list[ScannedRom] | None:
    """Devuelve las ROMs del 7z, o None si no contiene ninguna entrada soportada."""
    stat = path.stat()
    roms: list[ScannedRom] = []
    with py7zr.SevenZipFile(path) as archive:
        entries = [info for info in archive.list() if not info.is_directory and Path(info.filename).suffix.lower() in rom_extensions]
        if not entries:
            return None
        pending = []
        cached_hashes: dict[str, RomHash] = {}
        for info in entries:
            cached = cache.get(str(path), info.filename, platform, info.uncompressed, stat.st_mtime_ns) if cache else None
            if cached is not None:
                cached_hashes[info.filename] = cached
            else:
                pending.append(info)
        data_map = _read_7z_entries(archive, [info.filename for info in pending], max((info.uncompressed for info in pending), default=1)) if pending else {}
    for info in entries:
        cached_hit = cached_hashes.get(info.filename)
        if cached_hit is not None:
            rom = _scan_payload(
                hashes=cached_hit,
                data_loader=partial(_read_single_7z_entry, path, info.filename, info.uncompressed),
                source_path=path,
                container_path=path,
                inner_path=info.filename,
                platform=platform,
                dat_index=dat_index,
            )
        else:
            buffer = data_map.get(info.filename)
            if buffer is None:
                continue
            data = buffer.read()
            hashes = hash_bytes(data, platform)
            if cache:
                cache.put(str(path), info.filename, platform, info.uncompressed, stat.st_mtime_ns, hashes)
            rom = _scan_payload(data=data, hashes=hashes, source_path=path, container_path=path, inner_path=info.filename, platform=platform, dat_index=dat_index)
        roms.append(rom)
    return roms


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
            roms = _scan_7z(path, platform, rom_extensions, dat_index, cache)
            return (roms, []) if roms is not None else ([], [str(path)])
        return [], [str(path)]
    except (OSError, zipfile.BadZipFile, py7zr.Bad7zFile):
        return [], [str(path)]


def scan_directory(
    input_path: Path,
    platform: Platform,
    dat_index: DatIndex | None = None,
    dat_path: Path | None = None,
    progress: ProgressCallback | None = None,
    hash_cache: Path | None = None,
    workers: int | None = None,
) -> ScanResult:
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
                for path, future in zip(paths, futures, strict=True):
                    yield path, future.result()
        else:
            for path in paths:
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
                "phase": "done",
                "current": total,
                "total": total,
                "path": "",
                "roms": len(result.roms),
                "matched": sum(1 for rom in result.roms if rom.dat_game is not None),
            }
        )
    return result
