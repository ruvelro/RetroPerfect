from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import py7zr

from retroperfect import scanner
from retroperfect.models import Platform


def _counting(monkeypatch):
    calls = {"count": 0}
    original_bytes = scanner.hash_bytes
    original_stream = scanner.hash_stream

    def counted_bytes(data, platform=Platform.NES):
        calls["count"] += 1
        return original_bytes(data, platform)

    def counted_stream(fh):
        calls["count"] += 1
        return original_stream(fh)

    monkeypatch.setattr(scanner, "hash_bytes", counted_bytes)
    monkeypatch.setattr(scanner, "hash_stream", counted_stream)
    return calls


def _make_sources(tmp_path: Path) -> None:
    (tmp_path / "Game (Europe).nes").write_bytes(b"EUR")
    with zipfile.ZipFile(tmp_path / "Game (USA).zip", "w") as archive:
        archive.writestr("Game (USA).nes", b"USA")
    with py7zr.SevenZipFile(tmp_path / "Game (Japan).7z", "w") as archive:
        archive.writef(io.BytesIO(b"JPN"), "Game (Japan).nes")


def test_scan_cache_avoids_rehashing(tmp_path: Path, monkeypatch) -> None:
    _make_sources(tmp_path)
    cache = tmp_path / "cache" / "scan-cache.sqlite3"
    calls = _counting(monkeypatch)

    first = scanner.scan_directory(tmp_path, Platform.NES, hash_cache=cache)
    assert len(first.roms) == 3
    assert calls["count"] == 3

    calls["count"] = 0
    second = scanner.scan_directory(tmp_path, Platform.NES, hash_cache=cache)
    assert calls["count"] == 0
    assert {rom.hashes.md5 for rom in second.roms} == {rom.hashes.md5 for rom in first.roms}


def test_scan_cache_invalidates_on_change(tmp_path: Path, monkeypatch) -> None:
    _make_sources(tmp_path)
    cache = tmp_path / "cache" / "scan-cache.sqlite3"
    calls = _counting(monkeypatch)
    scanner.scan_directory(tmp_path, Platform.NES, hash_cache=cache)

    target = tmp_path / "Game (Europe).nes"
    target.write_bytes(b"NUEVO CONTENIDO")
    os.utime(target, ns=(1, 1))
    calls["count"] = 0
    result = scanner.scan_directory(tmp_path, Platform.NES, hash_cache=cache)
    assert calls["count"] == 1
    changed = next(rom for rom in result.roms if rom.source_path.endswith("Game (Europe).nes"))
    assert changed.hashes.size == len(b"NUEVO CONTENIDO")


def test_scan_cache_preserves_headered_dat_fallback(tmp_path: Path, monkeypatch) -> None:
    import binascii
    import hashlib

    from retroperfect.dat import DatIndex, parse_logiqx_dat

    payload = b"EUR"
    header = bytes.fromhex("4E45531A") + bytes(12)
    full = header + payload
    dat = tmp_path / "nes-headered.xml"
    dat.write_text(
        f"""<datafile><header><name>NES Headered</name></header>
<game name="Game (USA)"><rom name="Game (USA).nes" size="{len(full)}" crc="{binascii.crc32(full) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(full).hexdigest()}" sha1="{hashlib.sha1(full).hexdigest()}" header="4E 45 53 1A 00 00 00 00 00 00 00 00 00 00 00 00"/></game>
</datafile>""",
        encoding="utf-8",
    )
    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    (roms_dir / "Game (USA).nes").write_bytes(payload)
    index = DatIndex(parse_logiqx_dat(dat))
    cache = tmp_path / "cache.sqlite3"

    first = scanner.scan_directory(roms_dir, Platform.NES, dat_index=index, hash_cache=cache)
    assert first.roms[0].dat_game is not None

    calls = _counting(monkeypatch)
    second = scanner.scan_directory(roms_dir, Platform.NES, dat_index=index, hash_cache=cache)
    assert calls["count"] == 0
    assert second.roms[0].dat_game is not None


def test_parallel_scan_matches_sequential_results(tmp_path: Path) -> None:
    for index in range(12):
        (tmp_path / f"Game {index} (Europe).nes").write_bytes(f"payload-{index}".encode())
    with zipfile.ZipFile(tmp_path / "Pack (USA).zip", "w") as archive:
        for index in range(4):
            archive.writestr(f"Packed {index} (USA).nes", f"packed-{index}".encode())

    sequential = scanner.scan_directory(tmp_path, Platform.NES, workers=1)
    parallel = scanner.scan_directory(tmp_path, Platform.NES, workers=4)

    def key(scan):
        return sorted((rom.container_path, rom.inner_path or "", rom.hashes.md5) for rom in scan.roms)

    assert key(sequential) == key(parallel)
    assert len(parallel.roms) == 16
    assert sequential.unmatched_files == parallel.unmatched_files
