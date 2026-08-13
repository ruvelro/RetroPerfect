from __future__ import annotations

from pathlib import Path

import py7zr

from retroperfect.models import Platform
from retroperfect.scanner import scan_directory


def _make_7z(path: Path, entries: dict[str, bytes]) -> None:
    with py7zr.SevenZipFile(path, "w") as archive:
        for name, data in entries.items():
            import io

            archive.writef(io.BytesIO(data), name)


def test_scan_reads_roms_inside_7z(tmp_path: Path) -> None:
    _make_7z(tmp_path / "Game (Europe).7z", {"Game (Europe).nes": b"EUR", "readme.txt": b"ignorar"})
    scan = scan_directory(tmp_path, Platform.NES)
    assert len(scan.roms) == 1
    rom = scan.roms[0]
    assert rom.inner_path == "Game (Europe).nes"
    assert rom.metadata.regions == ["Europe"]
    assert scan.unmatched_files == []


def test_scan_marks_7z_without_roms_as_unmatched(tmp_path: Path) -> None:
    _make_7z(tmp_path / "docs.7z", {"readme.txt": b"nada"})
    scan = scan_directory(tmp_path, Platform.NES)
    assert scan.roms == []
    assert len(scan.unmatched_files) == 1


def test_scan_marks_corrupt_7z_as_unmatched(tmp_path: Path) -> None:
    (tmp_path / "roto.7z").write_bytes(b"esto no es un 7z")
    scan = scan_directory(tmp_path, Platform.NES)
    assert scan.roms == []
    assert len(scan.unmatched_files) == 1


def test_scan_skips_oversized_7z_entries(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import scanner

    monkeypatch.setattr(scanner, "MAX_7Z_ENTRY_BYTES", 4)
    _make_7z(tmp_path / "Pack (USA).7z", {"Pequeno (USA).nes": b"OK", "Enorme (USA).nes": b"X" * 100})
    scan = scanner.scan_directory(tmp_path, Platform.NES)
    assert len(scan.roms) == 1
    assert scan.roms[0].inner_path == "Pequeno (USA).nes"
    assert len(scan.unmatched_files) == 1
    assert "límite de extracción" in scan.unmatched_files[0]
