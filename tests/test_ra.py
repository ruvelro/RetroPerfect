from __future__ import annotations

import hashlib
import json

from retroperfect.hashing import hash_bytes
from retroperfect.models import Platform, ScanResult, ScannedRom, DetectedMetadata
from retroperfect.ra import annotate_scan_with_ra, init_cache


def test_annotate_scan_includes_ra_patch_metadata(tmp_path) -> None:
    cache = tmp_path / "ra.sqlite3"
    md5 = hashlib.md5(b"ROM").hexdigest()
    conn = init_cache(cache)
    with conn:
        conn.execute(
            """
            INSERT INTO ra_hashes(platform, hash, game_id, title, hash_name, labels, patch_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                Platform.NES.value,
                md5,
                1,
                "Game",
                "Game (USA) (Patched).nes",
                json.dumps(["nointro", "rapatches"]),
                "https://github.com/RetroAchievements/RAPatches/raw/main/NES/Game.zip",
            ),
        )
    conn.close()
    scan = ScanResult(
        id="scan",
        platform=Platform.NES,
        input_path=str(tmp_path),
        roms=[
            ScannedRom(
                id="rom",
                source_path=str(tmp_path / "Game.nes"),
                container_path=str(tmp_path / "Game.nes"),
                platform=Platform.NES,
                hashes=hash_bytes(b"ROM", Platform.NES),
                metadata=DetectedMetadata(title="Game"),
            )
        ],
    )
    annotated = annotate_scan_with_ra(scan, cache)
    assert annotated.roms[0].ra_game_id == 1
    assert annotated.roms[0].ra_hash_name == "Game (USA) (Patched).nes"
    assert "rapatches" in annotated.roms[0].ra_labels
    assert annotated.roms[0].ra_patch_url
