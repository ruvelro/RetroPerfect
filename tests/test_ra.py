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


def _cache_con_parches(tmp_path, filas: list[tuple[str, str, str]]):
    """filas: (hash, título del juego, nombre del hash). Todas con parche."""
    cache = tmp_path / "ra.sqlite3"
    conn = init_cache(cache)
    with conn:
        for indice, (md5, title, hash_name) in enumerate(filas, start=1):
            conn.execute(
                "INSERT INTO ra_hashes(platform, hash, game_id, title, hash_name, labels, patch_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (Platform.NES.value, md5, indice, title, hash_name, json.dumps(["rapatches"]), f"https://ejemplo.org/{indice}.zip"),
            )
    conn.close()
    return cache


def test_el_indice_de_parches_agrupa_por_titulo_normalizado(tmp_path) -> None:
    from retroperfect.ra import find_ra_patch_candidates, ra_patch_index

    cache = _cache_con_parches(
        tmp_path,
        [
            ("a" * 32, "Super Mario Bros", "Super Mario Bros (USA).nes"),
            ("b" * 32, "Otro Juego", "Otro Juego (Europe).nes"),
        ],
    )

    index = ra_patch_index(Platform.NES, cache)

    assert sorted(index) == ["otro juego", "super mario bros"]
    # El índice y la consulta suelta tienen que dar lo mismo: la curación usa
    # el primero y los tests/la CLI la segunda.
    assert [c.md5 for c in index["super mario bros"]] == [c.md5 for c in find_ra_patch_candidates(Platform.NES, "Super-Mario_Bros", cache)]


def test_un_parche_se_encuentra_por_el_titulo_del_hash_y_por_el_del_juego(tmp_path) -> None:
    """Los dos títulos no siempre coinciden y hay que poder llegar por ambos."""
    from retroperfect.ra import find_ra_patch_candidates, ra_patch_index

    cache = _cache_con_parches(tmp_path, [("c" * 32, "Probotector", "Contra (USA).nes")])
    index = ra_patch_index(Platform.NES, cache)

    assert len(index["probotector"]) == 1
    assert len(index["contra"]) == 1
    assert len(find_ra_patch_candidates(Platform.NES, "Contra", cache)) == 1, "sin duplicados al llegar por un solo título"


def test_annotate_cruza_en_memoria_con_una_consulta_por_plataforma(tmp_path, monkeypatch) -> None:
    """Era una consulta por ROM: 20.000 archivos eran 20.000 consultas."""
    from retroperfect import ra as ra_module

    cache = _cache_con_parches(tmp_path, [(hashlib.md5(f"ROM{i}".encode()).hexdigest(), f"Juego {i}", f"Juego {i}.nes") for i in range(5)])
    scan = ScanResult(
        id="scan",
        platform=Platform.NES,
        input_path=str(tmp_path),
        roms=[
            ScannedRom(
                id=f"rom{i}",
                source_path=str(tmp_path / f"Juego {i}.nes"),
                container_path=str(tmp_path / f"Juego {i}.nes"),
                platform=Platform.NES,
                hashes=hash_bytes(f"ROM{i}".encode(), Platform.NES),
                metadata=DetectedMetadata(title=f"Juego {i}"),
            )
            for i in range(5)
        ],
    )
    consultas: list[str] = []
    original = ra_module.init_cache

    def cache_rastreada(path=None):
        conn = original(path)
        conn.set_trace_callback(lambda sql: consultas.append(sql) if "FROM ra_hashes" in sql else None)
        return conn

    monkeypatch.setattr(ra_module, "init_cache", cache_rastreada)
    annotated = ra_module.annotate_scan_with_ra(scan, cache)

    assert [rom.ra_game_id for rom in annotated.roms] == [1, 2, 3, 4, 5]
    assert len(consultas) == 1, f"una consulta por plataforma, no por ROM: {len(consultas)}"
