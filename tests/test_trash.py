from __future__ import annotations

from pathlib import Path

import pytest

from retroperfect.manifest_io import apply_manifest
from retroperfect.models import ActionMode, Manifest, ManifestEntry, OutputBucket, Platform
from retroperfect.trash import empty_trash, list_sessions, restore_session


def _delete_manifest(paths: list[Path]) -> Manifest:
    return Manifest(
        id="m",
        scan_id="s",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[ManifestEntry(bucket=OutputBucket.MAIN, action=ActionMode.DELETE, source_path=str(path), rom_id=str(path)) for path in paths],
    )


def test_trash_sessions_are_listed_and_restorable(tmp_path: Path) -> None:
    rom = tmp_path / "roms" / "Juego (Europe).nes"
    rom.parent.mkdir()
    rom.write_bytes(b"data")
    trash = tmp_path / "trash"
    apply_manifest(_delete_manifest([rom]), confirm=True, trash_dir=trash)
    assert not rom.exists()

    sessions = list_sessions(trash)
    assert len(sessions) == 1
    assert sessions[0].files == 1
    assert sessions[0].restorable

    log = restore_session(sessions[0].name, root=trash)
    assert rom.exists()
    assert rom.read_bytes() == b"data"
    assert any("restaurado" in line for line in log)
    assert list_sessions(trash) == []


def test_trash_restore_skips_existing_originals(tmp_path: Path) -> None:
    rom = tmp_path / "Juego (USA).nes"
    rom.write_bytes(b"v1")
    trash = tmp_path / "trash"
    apply_manifest(_delete_manifest([rom]), confirm=True, trash_dir=trash)
    rom.write_bytes(b"v2-nuevo")  # el original reaparece con otro contenido

    session = list_sessions(trash)[0]
    log = restore_session(session.name, root=trash)
    assert rom.read_bytes() == b"v2-nuevo"
    assert any("el original ya existe" in line for line in log)
    # la sesión se conserva porque queda un archivo sin restaurar
    assert list_sessions(trash)[0].files == 1


def test_empty_trash_removes_everything(tmp_path: Path) -> None:
    rom_a = tmp_path / "a.nes"
    rom_b = tmp_path / "b.nes"
    rom_a.write_bytes(b"A")
    rom_b.write_bytes(b"B")
    trash = tmp_path / "trash"
    apply_manifest(_delete_manifest([rom_a, rom_b]), confirm=True, trash_dir=trash)
    assert empty_trash(trash) == 2
    assert list_sessions(trash) == []


def test_restore_unknown_session_fails(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="No existe"):
        restore_session("20990101-000000", root=tmp_path / "trash")
