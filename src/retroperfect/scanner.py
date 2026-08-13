from __future__ import annotations

import uuid
import zipfile
from pathlib import Path
from typing import Callable

from .dat import DatIndex
from .hashing import hash_bytes
from .metadata import parse_no_intro_name
from .models import Platform, ScanResult, ScannedRom
from .platforms import platform_spec


ProgressCallback = Callable[[dict[str, object]], None]


def _scan_payload(
    *,
    data: bytes,
    source_path: Path,
    container_path: Path,
    inner_path: str | None,
    platform: Platform,
    dat_index: DatIndex | None,
) -> ScannedRom:
    hashes = hash_bytes(data, platform)
    display_filename = inner_path or source_path.name
    dat_game = dat_index.match_data(data, hashes, filename=display_filename) if dat_index else None
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


def _scan_arcade_container(
    *,
    path: Path,
    platform: Platform,
    dat_index: DatIndex | None,
) -> ScannedRom:
    data = path.read_bytes()
    hashes = hash_bytes(data, platform)
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


def scan_directory(
    input_path: Path,
    platform: Platform,
    dat_index: DatIndex | None = None,
    dat_path: Path | None = None,
    progress: ProgressCallback | None = None,
) -> ScanResult:
    result = ScanResult(id=str(uuid.uuid4()), platform=platform, input_path=str(input_path), dat_path=str(dat_path) if dat_path else None)
    spec = platform_spec(platform)
    supported_extensions = set(spec.extensions)
    supported_rom_extensions = set(spec.rom_extensions)
    arcade_mode = spec.kind == "arcade"
    all_paths = [input_path] if input_path.is_file() else sorted(input_path.rglob("*"))
    paths = [path for path in all_paths if path.is_file() and path.suffix.lower() in supported_extensions]
    seen_containers: set[str] = set()
    total = len(paths)
    if progress:
        progress({"phase": "start", "current": 0, "total": total, "path": "", "roms": 0, "matched": 0})

    for index, path in enumerate(paths, start=1):
        try:
            if arcade_mode:
                rom = _scan_arcade_container(path=path, platform=platform, dat_index=dat_index)
                result.roms.append(rom)
                seen_containers.add(str(path))
            elif path.suffix.lower() in supported_rom_extensions:
                rom = _scan_payload(data=path.read_bytes(), source_path=path, container_path=path, inner_path=None, platform=platform, dat_index=dat_index)
                result.roms.append(rom)
                seen_containers.add(str(path))
            elif path.suffix.lower() == ".zip":
                with zipfile.ZipFile(path) as archive:
                    rom_entries = [info for info in archive.infolist() if not info.is_dir() and Path(info.filename).suffix.lower() in supported_rom_extensions]
                    if not rom_entries:
                        result.unmatched_files.append(str(path))
                        continue
                    for info in rom_entries:
                        data = archive.read(info)
                        rom = _scan_payload(data=data, source_path=path, container_path=path, inner_path=info.filename, platform=platform, dat_index=dat_index)
                        result.roms.append(rom)
                        seen_containers.add(str(path))
            else:
                result.unmatched_files.append(str(path))
        except (OSError, zipfile.BadZipFile):
            result.unmatched_files.append(str(path))
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
