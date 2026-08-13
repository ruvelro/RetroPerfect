from retroperfect.coverage import build_coverage
from retroperfect.models import DatCatalog, DatGame, DatRom, Platform, RomHash, ScanResult, ScannedRom, DetectedMetadata


def test_coverage_counts_games_independent_of_region() -> None:
    catalog = DatCatalog(
        games=[
            DatGame(name="Game (USA)", cloneof="Game", releases=["USA"], roms=[DatRom(name="Game (USA).nes")]),
            DatGame(name="Game (Europe)", cloneof="Game", releases=["Europe"], roms=[DatRom(name="Game (Europe).nes")]),
            DatGame(name="Missing (Europe)", releases=["Europe"], roms=[DatRom(name="Missing (Europe).nes")]),
        ]
    )
    scan = ScanResult(
        id="scan",
        platform=Platform.NES,
        input_path="roms",
        roms=[
            ScannedRom(
                id="rom",
                source_path="Game (Europe).nes",
                container_path="Game (Europe).nes",
                platform=Platform.NES,
                hashes=RomHash(crc32="1", md5="2", sha1="3", size=4),
                dat_game=catalog.games[1],
                metadata=DetectedMetadata(title="Game", regions=["Europe"]),
            )
        ],
    )
    summary = build_coverage(scan, catalog)
    assert summary.dat_games == 2
    assert summary.romset_games == 1
    assert summary.matched_games == 1
    assert summary.missing_from_romset == 1


def test_coverage_separates_outside_dat_from_hash_mismatch() -> None:
    catalog = DatCatalog(games=[DatGame(name="Game", releases=["Europe"], roms=[DatRom(name="Game.nes")])])
    scan = ScanResult(
        id="scan",
        platform=Platform.NES,
        input_path="roms",
        roms=[
            ScannedRom(
                id="rom",
                source_path="Game.nes",
                container_path="Game.nes",
                platform=Platform.NES,
                hashes=RomHash(crc32="1", md5="2", sha1="3", size=4),
                dat_game=None,
                metadata=DetectedMetadata(title="Game", regions=["Europe"]),
            )
        ],
    )
    summary = build_coverage(scan, catalog)
    assert summary.unmatched_romset_games == 0
    assert summary.hash_mismatch_games == 1


def test_coverage_collapses_regions_without_parent_clone() -> None:
    catalog = DatCatalog(
        games=[
            DatGame(name="Game (Spain)", releases=["Spain"], roms=[DatRom(name="Game (Spain).nes")]),
            DatGame(name="Game (USA)", releases=["USA"], roms=[DatRom(name="Game (USA).nes")]),
        ]
    )
    scan = ScanResult(
        id="scan",
        platform=Platform.NES,
        input_path="roms",
        roms=[
            ScannedRom(
                id="rom",
                source_path="Game (Spain).nes",
                container_path="Game (Spain).nes",
                platform=Platform.NES,
                hashes=RomHash(crc32="1", md5="2", sha1="3", size=4),
                dat_game=catalog.games[0],
                metadata=DetectedMetadata(title="Game", regions=["Spain"]),
            )
        ],
    )
    summary = build_coverage(scan, catalog)
    assert summary.dat_games == 1
    assert summary.rows[0].dat_variants == 2
