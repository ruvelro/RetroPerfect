from __future__ import annotations

import binascii
import hashlib
from pathlib import Path

from retroperfect.coverage import build_coverage
from retroperfect.dat import DatIndex, parse_logiqx_dat
from retroperfect.diagnostics import build_perfect_audit, build_patch_queue, detect_dat_warnings
from retroperfect.models import ActionMode, Manifest, ManifestEntry, OutputBucket, Platform
from retroperfect.profile import list_recommended_profiles
from retroperfect.scanner import scan_directory


def test_recommended_profiles_are_available() -> None:
    profiles = list_recommended_profiles()
    assert {"1G1R puro", "1G1R + RA", "España/Europa", "USA-first"} <= set(profiles)
    assert profiles["1G1R + RA"].auto_patch_ra is True
    assert profiles["USA-first"].outputs[0].region_priority[0] == "USA"


def test_nes_dat_warning_for_headered_dat_with_unheadered_romset(tmp_path: Path) -> None:
    payload = b"ROM"
    rom = tmp_path / "Game (Europe).unh"
    rom.write_bytes(payload)
    dat = tmp_path / "Nintendo - Nintendo Entertainment System (Headered).xml"
    full = b"NES\x1a" + bytes(12) + payload
    dat.write_text(
        f"""<datafile>
  <header><name>NES Headered</name></header>
  <game name="Game (Europe)"><description>Game (Europe)</description><rom name="Game (Europe).nes" size="{len(full)}" crc="{binascii.crc32(full) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(full).hexdigest()}" sha1="{hashlib.sha1(full).hexdigest()}"/></game>
</datafile>""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES)
    rows = detect_dat_warnings(Platform.NES, tmp_path, dat, scan)
    assert any("unheadered" in row.detail.lower() for row in rows)


def test_n64_dat_warning_for_endian_mismatch(tmp_path: Path) -> None:
    rom = tmp_path / "Game.v64"
    rom.write_bytes(b"\x37\x80\x40\x12DATA")
    dat = tmp_path / "Nintendo - Nintendo 64 (BigEndian).xml"
    dat.write_text("<datafile><header><name>Nintendo - Nintendo 64 BigEndian</name></header></datafile>", encoding="utf-8")
    scan = scan_directory(tmp_path, Platform.N64)
    rows = detect_dat_warnings(Platform.N64, tmp_path, dat, scan)
    assert any("endian" in row.item.lower() and "ByteSwapped" in row.detail for row in rows)


def test_perfect_audit_and_patch_queue(tmp_path: Path) -> None:
    payload = b"ROM"
    (tmp_path / "Game (Europe).nes").write_bytes(payload)
    dat = tmp_path / "nes.xml"
    dat.write_text(
        f"""<datafile>
  <game name="Game (Europe)"><description>Game (Europe)</description><release name="Game" region="Europe"/><rom name="Game (Europe).nes" size="{len(payload)}" crc="{binascii.crc32(payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(payload).hexdigest()}" sha1="{hashlib.sha1(payload).hexdigest()}"/></game>
</datafile>""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES, DatIndex(parse_logiqx_dat(dat)), dat)
    manifest = Manifest(
        id="manifest",
        scan_id=scan.id,
        platform=Platform.NES,
        profile_snapshot={},
        entries=[
            ManifestEntry(
                bucket=OutputBucket.RA,
                action=ActionMode.COPY,
                source_path=scan.roms[0].container_path,
                destination_path=str(tmp_path / "out" / "Otros" / "RetroAchievements" / "Game RA.nes"),
                rom_id=scan.roms[0].id,
                patch_url="https://example.test/Game.ips",
                patch_expected_md5="abc",
            )
        ],
    )
    summary = build_coverage(scan, parse_logiqx_dat(dat), manifest)
    audit = build_perfect_audit(summary, scan, manifest)
    assert audit.patch_pending == 1
    assert build_patch_queue(manifest)[0].status == "Listo"
