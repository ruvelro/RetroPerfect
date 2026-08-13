from pathlib import Path
import zipfile
import hashlib
import binascii
import json

from retroperfect.dat import DatIndex, parse_dat, parse_logiqx_dat
from retroperfect.models import ActionMode, ExportLayout, OutputBucket, Platform, ProfileOutput, SelectionProfile
from retroperfect.profile import DEFAULT_PROFILE
from retroperfect.ra import init_cache
from retroperfect.rules import build_manifest
from retroperfect.scanner import scan_directory


def test_scan_zip_and_keep_main_and_ra(tmp_path: Path) -> None:
    eur_payload = b"EUR"
    usa_payload = b"USA"
    eur = tmp_path / "Game (Europe).nes"
    eur.write_bytes(eur_payload)
    zipped = tmp_path / "Game (USA).zip"
    with zipfile.ZipFile(zipped, "w") as archive:
        archive.writestr("Game (USA).nes", usa_payload)
    eur_crc = binascii.crc32(eur_payload) & 0xFFFFFFFF
    usa_crc = binascii.crc32(usa_payload) & 0xFFFFFFFF

    dat = tmp_path / "nes.xml"
    dat.write_text(
        f"""<datafile>
  <header><name>NES</name></header>
  <game name="Game (Europe)" cloneof="Game"><description>Game (Europe)</description><release name="Game" region="Europe"/><rom name="Game (Europe).nes" size="{len(eur_payload)}" crc="{eur_crc:08x}" md5="{hashlib.md5(eur_payload).hexdigest()}" sha1="{hashlib.sha1(eur_payload).hexdigest()}"/></game>
  <game name="Game (USA)" cloneof="Game"><description>Game (USA)</description><release name="Game" region="USA"/><rom name="Game (USA).nes" size="{len(usa_payload)}" crc="{usa_crc:08x}" md5="{hashlib.md5(usa_payload).hexdigest()}" sha1="{hashlib.sha1(usa_payload).hexdigest()}"/></game>
</datafile>""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES, dat_index=DatIndex(parse_logiqx_dat(dat)), dat_path=dat)
    for rom in scan.roms:
        if rom.inner_path == "Game (USA).nes":
            rom.ra_game_id = 1
            rom.ra_title = "Game"
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN, OutputBucket.RA], output_dir=tmp_path / "out", action=ActionMode.COPY)
    assert len(manifest.entries) == 2
    assert any(entry.bucket == OutputBucket.MAIN and entry.source_path.endswith("Game (Europe).nes") for entry in manifest.entries)
    assert any(entry.bucket == OutputBucket.RA and entry.source_path.endswith("Game (USA).zip") for entry in manifest.entries)


def test_manual_override_wins(tmp_path: Path) -> None:
    eur = tmp_path / "Game (Europe).nes"
    usa = tmp_path / "Game (USA).nes"
    eur.write_bytes(b"EUR")
    usa.write_bytes(b"USA")
    scan = scan_directory(tmp_path, Platform.NES)
    usa_rom = next(rom for rom in scan.roms if rom.source_path.endswith("Game (USA).nes"))
    flexible_profile = SelectionProfile(outputs=[ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=False)])
    manifest = build_manifest(
        scan,
        flexible_profile,
        [OutputBucket.MAIN],
        output_dir=tmp_path / "out",
        action=ActionMode.COPY,
        overrides={"main": {"Game": usa_rom.id}},
    )
    assert len(manifest.entries) == 1
    assert manifest.entries[0].source_path.endswith("Game (USA).nes")
    assert "manual override" in " ".join(manifest.entries[0].explanation).lower()


def test_strict_1g1r_excludes_roms_without_dat_match(tmp_path: Path) -> None:
    rom = tmp_path / "Homebrew (World).nes"
    rom.write_bytes(b"HB")
    scan = scan_directory(tmp_path, Platform.NES)
    profile = SelectionProfile(outputs=[ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=True)])
    manifest = build_manifest(scan, profile, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)
    assert manifest.entries == []
    assert any("strict 1g1r" in " ".join(decision.reasons).lower() for decision in manifest.discarded)


def test_strict_1g1r_collapses_regions_without_parent_clone(tmp_path: Path) -> None:
    spain_payload = b"ES"
    usa_payload = b"US"
    (tmp_path / "Game (Spain).nes").write_bytes(spain_payload)
    (tmp_path / "Game (USA).nes").write_bytes(usa_payload)
    dat = tmp_path / "nes.xml"
    dat.write_text(
        f"""<datafile>
  <game name="Game (Spain)"><description>Game (Spain)</description><release name="Game" region="Spain"/><rom name="Game (Spain).nes" size="{len(spain_payload)}" crc="{binascii.crc32(spain_payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(spain_payload).hexdigest()}" sha1="{hashlib.sha1(spain_payload).hexdigest()}"/></game>
  <game name="Game (USA)"><description>Game (USA)</description><release name="Game" region="USA"/><rom name="Game (USA).nes" size="{len(usa_payload)}" crc="{binascii.crc32(usa_payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(usa_payload).hexdigest()}" sha1="{hashlib.sha1(usa_payload).hexdigest()}"/></game>
</datafile>""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES, dat_index=DatIndex(parse_logiqx_dat(dat)), dat_path=dat)
    profile = SelectionProfile(outputs=[ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=True)])
    manifest = build_manifest(scan, profile, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)
    assert len(manifest.entries) == 1
    assert manifest.entries[0].source_path.endswith("Game (Spain).nes")


def test_ra_output_collapses_regions_without_parent_clone(tmp_path: Path) -> None:
    spain_payload = b"ES"
    usa_payload = b"US"
    (tmp_path / "Game (Spain).nes").write_bytes(spain_payload)
    (tmp_path / "Game (USA).nes").write_bytes(usa_payload)
    dat = tmp_path / "nes.xml"
    dat.write_text(
        f"""<datafile>
  <game name="Game (Spain)"><description>Game (Spain)</description><release name="Game" region="Spain"/><rom name="Game (Spain).nes" size="{len(spain_payload)}" crc="{binascii.crc32(spain_payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(spain_payload).hexdigest()}" sha1="{hashlib.sha1(spain_payload).hexdigest()}"/></game>
  <game name="Game (USA)"><description>Game (USA)</description><release name="Game" region="USA"/><rom name="Game (USA).nes" size="{len(usa_payload)}" crc="{binascii.crc32(usa_payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(usa_payload).hexdigest()}" sha1="{hashlib.sha1(usa_payload).hexdigest()}"/></game>
</datafile>""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES, dat_index=DatIndex(parse_logiqx_dat(dat)), dat_path=dat)
    for rom in scan.roms:
        rom.ra_game_id = 1
        rom.ra_title = "Game"
    profile = SelectionProfile(outputs=[ProfileOutput(bucket=OutputBucket.RA, require_ra=True, strict_1g1r=False)])
    manifest = build_manifest(scan, profile, [OutputBucket.RA], output_dir=tmp_path / "out", action=ActionMode.COPY)
    assert len(manifest.entries) == 1
    assert manifest.entries[0].source_path.endswith("Game (Spain).nes")


def test_organized_export_places_main_by_region_and_ra_extras_under_otros(tmp_path: Path) -> None:
    eur_payload = b"EUR"
    usa_payload = b"USA"
    (tmp_path / "Game (Europe).nes").write_bytes(eur_payload)
    zipped = tmp_path / "Game (USA).zip"
    with zipfile.ZipFile(zipped, "w") as archive:
        archive.writestr("Game (USA).nes", usa_payload)
    dat = tmp_path / "nes.xml"
    dat.write_text(
        f"""<datafile>
  <game name="Game (Europe)" cloneof="Game"><description>Game (Europe)</description><release name="Game" region="Europe"/><rom name="Game (Europe).nes" size="{len(eur_payload)}" crc="{binascii.crc32(eur_payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(eur_payload).hexdigest()}" sha1="{hashlib.sha1(eur_payload).hexdigest()}"/></game>
  <game name="Game (USA)" cloneof="Game"><description>Game (USA)</description><release name="Game" region="USA"/><rom name="Game (USA).nes" size="{len(usa_payload)}" crc="{binascii.crc32(usa_payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(usa_payload).hexdigest()}" sha1="{hashlib.sha1(usa_payload).hexdigest()}"/></game>
</datafile>""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES, dat_index=DatIndex(parse_logiqx_dat(dat)), dat_path=dat)
    for rom in scan.roms:
        if rom.inner_path == "Game (USA).nes":
            rom.ra_game_id = 1
            rom.ra_title = "Game"
    profile = SelectionProfile(
        export_layout=ExportLayout.ORGANIZED,
        outputs=[
            ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=True),
            ProfileOutput(bucket=OutputBucket.RA, require_ra=True, strict_1g1r=False),
        ],
    )
    manifest = build_manifest(scan, profile, [OutputBucket.MAIN, OutputBucket.RA], output_dir=tmp_path / "out", action=ActionMode.COPY)
    destinations = {entry.bucket: Path(entry.destination_path or "") for entry in manifest.entries}
    assert destinations[OutputBucket.MAIN] == tmp_path / "out" / "EUR" / "Game (Europe).nes"
    assert destinations[OutputBucket.RA] == tmp_path / "out" / "Otros" / "RetroAchievements" / "Game (USA).zip"


def test_ra_extra_follows_ra_profile_and_keeps_one_supported_region(tmp_path: Path) -> None:
    eur_payload = b"EUR"
    usa_payload = b"USA"
    jpn_payload = b"JPN"
    (tmp_path / "Game (Europe).nes").write_bytes(eur_payload)
    (tmp_path / "Game (USA).nes").write_bytes(usa_payload)
    (tmp_path / "Game (Japan).nes").write_bytes(jpn_payload)
    dat = tmp_path / "nes.xml"
    dat.write_text(
        f"""<datafile>
  <game name="Game (Europe)" cloneof="Game"><description>Game (Europe)</description><release name="Game" region="Europe"/><rom name="Game (Europe).nes" size="{len(eur_payload)}" crc="{binascii.crc32(eur_payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(eur_payload).hexdigest()}" sha1="{hashlib.sha1(eur_payload).hexdigest()}"/></game>
  <game name="Game (USA)" cloneof="Game"><description>Game (USA)</description><release name="Game" region="USA"/><rom name="Game (USA).nes" size="{len(usa_payload)}" crc="{binascii.crc32(usa_payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(usa_payload).hexdigest()}" sha1="{hashlib.sha1(usa_payload).hexdigest()}"/></game>
  <game name="Game (Japan)" cloneof="Game"><description>Game (Japan)</description><release name="Game" region="Japan"/><rom name="Game (Japan).nes" size="{len(jpn_payload)}" crc="{binascii.crc32(jpn_payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(jpn_payload).hexdigest()}" sha1="{hashlib.sha1(jpn_payload).hexdigest()}"/></game>
</datafile>""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES, dat_index=DatIndex(parse_logiqx_dat(dat)), dat_path=dat)
    for rom in scan.roms:
        if "USA" in rom.source_path or "Japan" in rom.source_path:
            rom.ra_game_id = 1
            rom.ra_title = "Game"
    profile = SelectionProfile(
        export_layout=ExportLayout.ORGANIZED,
        outputs=[
            ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=True),
            ProfileOutput(bucket=OutputBucket.RA, require_ra=True, strict_1g1r=False),
        ],
    )
    manifest = build_manifest(scan, profile, [OutputBucket.MAIN, OutputBucket.RA], output_dir=tmp_path / "out", action=ActionMode.COPY)
    assert len(manifest.entries) == 2
    ra_entry = next(entry for entry in manifest.entries if entry.bucket == OutputBucket.RA)
    assert ra_entry.source_path.endswith("Game (USA).nes")
    assert Path(ra_entry.destination_path or "") == tmp_path / "out" / "Otros" / "RetroAchievements" / "Game (USA).nes"


def test_main_can_prefer_ra_variant_over_newer_revision(tmp_path: Path) -> None:
    old_payload = b"OLDRA"
    new_payload = b"NEWNO"
    (tmp_path / "Game (USA) (Rev 1).nes").write_bytes(old_payload)
    (tmp_path / "Game (USA) (Rev 3).nes").write_bytes(new_payload)
    dat = tmp_path / "nes.xml"
    dat.write_text(
        f"""<datafile>
  <game name="Game (USA) (Rev 1)" cloneof="Game"><description>Game (USA) (Rev 1)</description><release name="Game" region="USA"/><rom name="Game (USA) (Rev 1).nes" size="{len(old_payload)}" crc="{binascii.crc32(old_payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(old_payload).hexdigest()}" sha1="{hashlib.sha1(old_payload).hexdigest()}"/></game>
  <game name="Game (USA) (Rev 3)" cloneof="Game"><description>Game (USA) (Rev 3)</description><release name="Game" region="USA"/><rom name="Game (USA) (Rev 3).nes" size="{len(new_payload)}" crc="{binascii.crc32(new_payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(new_payload).hexdigest()}" sha1="{hashlib.sha1(new_payload).hexdigest()}"/></game>
</datafile>""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES, dat_index=DatIndex(parse_logiqx_dat(dat)), dat_path=dat)
    for rom in scan.roms:
        if "Rev 1" in rom.source_path:
            rom.ra_game_id = 1
            rom.ra_title = "Game"
    profile = SelectionProfile(
        outputs=[
            ProfileOutput(
                bucket=OutputBucket.MAIN,
                strict_1g1r=True,
                prefer_newest_revision=True,
                prefer_ra_compatible=True,
                region_priority=["USA"],
            )
        ]
    )
    manifest = build_manifest(scan, profile, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)
    assert len(manifest.entries) == 1
    assert manifest.entries[0].source_path.endswith("Game (USA) (Rev 1).nes")


def test_organized_export_does_not_duplicate_ra_when_main_already_has_it(tmp_path: Path) -> None:
    payload = b"EUR"
    (tmp_path / "Game (Europe).nes").write_bytes(payload)
    dat = tmp_path / "nes.xml"
    dat.write_text(
        f"""<datafile>
  <game name="Game (Europe)"><description>Game (Europe)</description><release name="Game" region="Europe"/><rom name="Game (Europe).nes" size="{len(payload)}" crc="{binascii.crc32(payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(payload).hexdigest()}" sha1="{hashlib.sha1(payload).hexdigest()}"/></game>
</datafile>""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES, dat_index=DatIndex(parse_logiqx_dat(dat)), dat_path=dat)
    scan.roms[0].ra_game_id = 1
    scan.roms[0].ra_title = "Game"
    profile = SelectionProfile(
        export_layout=ExportLayout.ORGANIZED,
        outputs=[
            ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=True),
            ProfileOutput(bucket=OutputBucket.RA, require_ra=True, strict_1g1r=False),
        ],
    )
    manifest = build_manifest(scan, profile, [OutputBucket.MAIN, OutputBucket.RA], output_dir=tmp_path / "out", action=ActionMode.COPY)
    assert len(manifest.entries) == 1
    assert manifest.entries[0].destination_path == str(tmp_path / "out" / "EUR" / "Game (Europe).nes")


def test_organized_export_places_special_tags_under_otros(tmp_path: Path) -> None:
    rom = tmp_path / "Game (World) (Hack).nes"
    rom.write_bytes(b"HACK")
    scan = scan_directory(tmp_path, Platform.NES)
    profile = SelectionProfile(
        export_layout=ExportLayout.ORGANIZED,
        outputs=[ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=False)],
    )
    manifest = build_manifest(scan, profile, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)
    assert manifest.entries[0].destination_path == str(tmp_path / "out" / "Otros" / "Hacks" / "Game (World) (Hack).nes")


def test_auto_patch_ra_creates_patch_manifest_entry_from_cache(tmp_path: Path) -> None:
    rom = tmp_path / "Game (Europe).nes"
    rom.write_bytes(b"CLEAN")
    scan = scan_directory(tmp_path, Platform.NES)
    cache = tmp_path / "ra.sqlite3"
    conn = init_cache(cache)
    with conn:
        conn.execute(
            """
            INSERT INTO ra_hashes(platform, hash, game_id, title, hash_name, labels, patch_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                Platform.NES.value,
                hashlib.md5(b"PATCHED").hexdigest(),
                1,
                "Game",
                "Game (USA) (RA Patch).nes",
                json.dumps(["rapatches"]),
                "https://example.test/Game.zip",
            ),
        )
    conn.close()
    profile = SelectionProfile(
        export_layout=ExportLayout.ORGANIZED,
        auto_patch_ra=True,
        outputs=[ProfileOutput(bucket=OutputBucket.RA, require_ra=True, strict_1g1r=False)],
    )
    manifest = build_manifest(scan, profile, [OutputBucket.RA], output_dir=tmp_path / "out", action=ActionMode.COPY, ra_cache=cache)
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.patch_url == "https://example.test/Game.zip"
    assert entry.patch_expected_md5 == hashlib.md5(b"PATCHED").hexdigest()
    assert entry.destination_path == str(tmp_path / "out" / "Otros" / "RetroAchievements" / "Game (USA) (RA Patch).nes")


def test_headered_nes_matches_unheadered_dat(tmp_path: Path) -> None:
    payload = b"NES-PAYLOAD"
    rom = tmp_path / "Game (Europe).nes"
    rom.write_bytes(b"NES\x1a" + bytes(12) + payload)
    dat = tmp_path / "nes.dat"
    dat.write_text(
        f"""clrmamepro ( name "NES Unheadered" )
game (
    name "Game (Europe)"
    rom ( name "Game (Europe).nes" size {len(payload)} crc {binascii.crc32(payload) & 0xFFFFFFFF:08x} md5 {hashlib.md5(payload).hexdigest()} sha1 {hashlib.sha1(payload).hexdigest()} )
)""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES, dat_index=DatIndex(parse_dat(dat)))
    assert scan.roms[0].dat_game is not None
    assert scan.roms[0].dat_game.name == "Game (Europe)"


def test_unh_inside_zip_matches_headered_dat(tmp_path: Path) -> None:
    payload = b"NES-PAYLOAD"
    header = b"NES\x1a" + bytes(12)
    zipped = tmp_path / "Game (Europe).zip"
    with zipfile.ZipFile(zipped, "w") as archive:
        archive.writestr("Game (Europe).unh", payload)
    full = header + payload
    dat = tmp_path / "nes-headered.xml"
    dat.write_text(
        f"""<datafile>
  <header><name>NES Headered</name></header>
  <game name="Game (Europe)" id="1"><description>Game (Europe)</description><rom name="Game (Europe).nes" size="{len(full)}" crc="{binascii.crc32(full) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(full).hexdigest()}" sha1="{hashlib.sha1(full).hexdigest()}" header="{header.hex(' ').upper()}"/></game>
</datafile>""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES, dat_index=DatIndex(parse_dat(dat)))
    assert len(scan.roms) == 1
    assert scan.roms[0].inner_path == "Game (Europe).unh"
    assert scan.roms[0].dat_game is not None


def test_scan_reports_progress(tmp_path: Path) -> None:
    rom = tmp_path / "Game (Europe).unh"
    rom.write_bytes(b"payload")
    updates = []
    scan = scan_directory(tmp_path, Platform.NES, progress=updates.append)
    assert len(scan.roms) == 1
    assert updates[0]["phase"] == "start"
    assert updates[-1]["phase"] == "done"
    assert updates[-1]["roms"] == 1


def _plain_rom(path: str, title: str):
    from retroperfect.metadata import parse_no_intro_name
    from retroperfect.models import RomHash, ScannedRom

    return ScannedRom(
        id=path,
        source_path=path,
        container_path=path,
        platform=Platform.NES,
        hashes=RomHash(crc32="0" * 8, md5="0" * 32, sha1="0" * 40, size=1),
        metadata=parse_no_intro_name(Path(path).name),
    )


def test_strict_exclusions_ignore_substrings_in_titles_and_paths() -> None:
    from retroperfect.rules import _special_folder, _strict_exclusions

    for name in ["Bad Dudes (USA).nes", "Demolition Man (USA).nes", "Sunland Quest (Europe).nes", "Promotion Chess (USA).nes"]:
        rom = _plain_rom(f"/roms/hacks-backup/{name}", name)
        assert _strict_exclusions(rom) == [], name
        assert _special_folder(rom) is None, name


def test_strict_exclusions_still_detect_real_tags() -> None:
    from retroperfect.rules import _special_folder, _strict_exclusions

    beta = _plain_rom("/roms/Game (USA) (Beta).nes", "Game")
    assert _strict_exclusions(beta) == ["Beta"]
    assert _special_folder(beta) == "Prototypes"
    unl = _plain_rom("/roms/Game (World) (Unl).nes", "Game")
    assert _strict_exclusions(unl) == ["Unl"]
    assert _special_folder(unl) == "Unlicensed"


def test_delete_manifest_targets_losers_not_winners(tmp_path: Path) -> None:
    (tmp_path / "Game (Spain).nes").write_bytes(b"ES")
    (tmp_path / "Game (USA).nes").write_bytes(b"US")
    scan = scan_directory(tmp_path, Platform.NES)
    profile = SelectionProfile(outputs=[ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=False)])
    manifest = build_manifest(scan, profile, [OutputBucket.MAIN], output_dir=None, action=ActionMode.DELETE)
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.action == ActionMode.DELETE
    assert entry.source_path.endswith("Game (USA).nes")
    assert entry.destination_path is None


def test_delete_manifest_protects_shared_containers(tmp_path: Path) -> None:
    zipped = tmp_path / "Game.zip"
    with zipfile.ZipFile(zipped, "w") as archive:
        archive.writestr("Game (Spain).nes", b"ES")
        archive.writestr("Game (USA).nes", b"US")
    scan = scan_directory(tmp_path, Platform.NES)
    profile = SelectionProfile(outputs=[ProfileOutput(bucket=OutputBucket.MAIN, strict_1g1r=False)])
    manifest = build_manifest(scan, profile, [OutputBucket.MAIN], output_dir=None, action=ActionMode.DELETE)
    assert manifest.entries == []
