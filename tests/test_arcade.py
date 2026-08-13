from __future__ import annotations

import zipfile
from pathlib import Path

from retroperfect.dat import DatIndex, parse_dat
from retroperfect.models import ActionMode, OutputBucket, Platform, ProfileOutput, SelectionProfile
from retroperfect.rules import build_manifest
from retroperfect.scanner import scan_directory


def _write_zip(path: Path, inner_name: str, payload: bytes) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(inner_name, payload)


def test_mame_machine_dat_matches_arcade_zip_by_set_name(tmp_path: Path) -> None:
    dat = tmp_path / "mame.xml"
    dat.write_text(
        """
<mame>
  <machine name="parent">
    <description>Parent Game</description>
    <rom name="p.rom" size="4" crc="11111111"/>
  </machine>
  <machine name="clone" cloneof="parent">
    <description>Parent Game Clone</description>
    <rom name="c.rom" size="4" crc="22222222"/>
  </machine>
</mame>
""",
        encoding="utf-8",
    )
    source = tmp_path / "roms"
    source.mkdir()
    _write_zip(source / "parent.zip", "p.rom", b"PPPP")
    _write_zip(source / "clone.zip", "c.rom", b"CCCC")

    catalog = parse_dat(dat)
    scan = scan_directory(source, Platform.MAME, DatIndex(catalog), dat)

    assert len(scan.roms) == 2
    assert {rom.dat_game.name for rom in scan.roms if rom.dat_game} == {"parent", "clone"}
    assert all(rom.inner_path is None for rom in scan.roms)


def test_arcade_safe_profile_does_not_collapse_clones_by_default(tmp_path: Path) -> None:
    dat = tmp_path / "mame.xml"
    dat.write_text(
        """
<mame>
  <machine name="parent"><description>Parent Game</description><rom name="p.rom" size="4" crc="11111111"/></machine>
  <machine name="clone" cloneof="parent"><description>Parent Game Clone</description><rom name="c.rom" size="4" crc="22222222"/></machine>
</mame>
""",
        encoding="utf-8",
    )
    source = tmp_path / "roms"
    source.mkdir()
    _write_zip(source / "parent.zip", "p.rom", b"PPPP")
    _write_zip(source / "clone.zip", "c.rom", b"CCCC")
    scan = scan_directory(source, Platform.MAME, DatIndex(parse_dat(dat)), dat)

    safe = SelectionProfile(outputs=[ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=False)])
    safe_manifest = build_manifest(scan, safe, [OutputBucket.MAIN], tmp_path / "out", ActionMode.COPY)
    assert len(safe_manifest.entries) == 2

    strict = SelectionProfile(outputs=[ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=True)])
    strict_manifest = build_manifest(scan, strict, [OutputBucket.MAIN], tmp_path / "out", ActionMode.COPY)
    assert len(strict_manifest.entries) == 1
