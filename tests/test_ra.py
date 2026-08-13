from __future__ import annotations

import hashlib
import json

from retroperfect.hashing import hash_bytes
from retroperfect.models import DetectedMetadata, Platform, ScannedRom, ScanResult
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


def test_sync_ra_hashes_skips_malformed_rows(tmp_path, monkeypatch) -> None:
    from retroperfect import ra
    from retroperfect.models import Platform

    monkeypatch.setattr(ra, "save_credentials", lambda user, key: tmp_path / "creds.json")
    rows = [
        {"ID": "10", "Title": "Good", "Hashes": ["AABB"]},
        {"Title": "Sin ID", "Hashes": ["CCDD"]},
        {"ID": "not-a-number", "Title": "Mal ID", "Hashes": ["EEFF"]},
        "no-dict",
        {"ID": 11, "Title": "String hash", "MD5": "1122"},
    ]
    monkeypatch.setattr(ra, "_request_json", lambda endpoint, params: rows)
    cache = tmp_path / "cache.sqlite3"
    count = ra.sync_ra_hashes(Platform.NES, username="user", api_key="key", cache=cache)
    assert count == 2
    assert ra.ra_cache_count(Platform.NES, cache=cache) == 2


def test_sync_ra_hashes_rejects_unexpected_payload(tmp_path, monkeypatch) -> None:
    import pytest

    from retroperfect import ra
    from retroperfect.models import Platform

    monkeypatch.setattr(ra, "save_credentials", lambda user, key: tmp_path / "creds.json")
    monkeypatch.setattr(ra, "_request_json", lambda endpoint, params: {"Error": "invalid key"})
    with pytest.raises(RuntimeError, match="inesperada"):
        ra.sync_ra_hashes(Platform.NES, username="user", api_key="key", cache=tmp_path / "cache.sqlite3")
