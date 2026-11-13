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


def test_una_cache_de_otra_version_se_descarta_entera(tmp_path: Path) -> None:
    """Servir hashes que ya no significan lo mismo es peor que re-hashear."""
    import sqlite3

    from retroperfect.models import RomHash
    from retroperfect.scan_cache import CACHE_SCHEMA_VERSION, ScanHashCache

    ruta = tmp_path / "cache.sqlite3"
    cache = ScanHashCache(ruta)
    cache.put("/roms/a.nes", None, Platform.NES, 10, 1, RomHash(crc32="a", md5="b", sha1="c", size=10))
    cache.close()
    with sqlite3.connect(ruta) as conn:
        conn.execute(f"PRAGMA user_version = {CACHE_SCHEMA_VERSION + 1}")

    reabierta = ScanHashCache(ruta)
    try:
        assert reabierta.get("/roms/a.nes", None, Platform.NES, 10, 1) is None
        assert int(reabierta.conn.execute("PRAGMA user_version").fetchone()[0]) == CACHE_SCHEMA_VERSION
    finally:
        reabierta.close()


def test_una_entrada_ilegible_se_recalcula_en_vez_de_romper_el_escaneo(tmp_path: Path) -> None:
    from retroperfect.models import RomHash
    from retroperfect.scan_cache import ScanHashCache

    cache = ScanHashCache(tmp_path / "cache.sqlite3")
    try:
        cache.put("/roms/a.nes", None, Platform.NES, 10, 1, RomHash(crc32="a", md5="b", sha1="c", size=10))
        cache.conn.execute("UPDATE file_hashes SET hashes = 'esto no es json'")

        assert cache.get("/roms/a.nes", None, Platform.NES, 10, 1) is None
    finally:
        cache.close()


def test_el_escaneo_se_puede_cancelar_entre_archivos(tmp_path: Path) -> None:
    """Un escaneo de cientos de GB tenía que terminar o cerrarse la app entera."""
    for i in range(20):
        (tmp_path / f"Juego {i} (Europe).nes").write_bytes(f"ROM{i}".encode())
    vistos: list[int] = []

    def cancelar_tras_tres() -> bool:
        vistos.append(1)
        return len(vistos) > 3

    fases: list[str] = []
    scan = scanner.scan_directory(
        tmp_path,
        Platform.NES,
        progress=lambda update: fases.append(str(update["phase"])),
        cancelled=cancelar_tras_tres,
        workers=2,
    )

    assert 0 < len(scan.roms) < 20, f"ni se cortó ni escaneó todo: {len(scan.roms)}"
    assert fases[-1] == "cancelled", "quien llama tiene que saber que la lista está incompleta"


def test_un_escaneo_sin_cancelar_termina_en_done(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"Juego {i} (Europe).nes").write_bytes(f"ROM{i}".encode())
    fases: list[str] = []

    scan = scanner.scan_directory(tmp_path, Platform.NES, progress=lambda update: fases.append(str(update["phase"])))

    assert len(scan.roms) == 3
    assert fases[-1] == "done"


def test_la_cache_se_exporta_y_se_vuelve_a_importar(tmp_path: Path) -> None:
    """Re-escanear cientos de GB cuesta horas: la caché tiene que poder salvarse."""
    from retroperfect.models import RomHash
    from retroperfect.scan_cache import ScanHashCache

    rom = tmp_path / "Juego (Europe).nes"
    rom.write_bytes(b"ROM")
    stat = rom.stat()
    origen = ScanHashCache(tmp_path / "a.sqlite3")
    hashes = RomHash(crc32="aabbccdd", md5="0" * 32, sha1="1" * 40, size=stat.st_size)
    origen.put(str(rom), None, Platform.NES, stat.st_size, stat.st_mtime_ns, hashes)
    filas = origen.export_rows()
    origen.close()

    destino = ScanHashCache(tmp_path / "b.sqlite3")
    try:
        assert destino.import_rows(filas) == 1
        assert destino.get(str(rom), None, Platform.NES, stat.st_size, stat.st_mtime_ns) == hashes
        assert destino.usable_rows() == 1
    finally:
        destino.close()


def test_una_coleccion_que_cambia_de_sitio_reutiliza_la_cache(tmp_path: Path) -> None:
    """Mover dentro del mismo sistema de archivos conserva el mtime, así que la
    caché sigue valiendo si se reapuntan las rutas."""
    from retroperfect.models import RomHash
    from retroperfect.scan_cache import ScanHashCache

    vieja = tmp_path / "volumen-viejo"
    nueva = tmp_path / "volumen-nuevo"
    vieja.mkdir()
    nueva.mkdir()
    rom = nueva / "Juego (Europe).nes"
    rom.write_bytes(b"ROM")
    stat = rom.stat()

    cache = ScanHashCache(tmp_path / "cache.sqlite3")
    try:
        filas = [
            {
                "container": str(vieja / "Juego (Europe).nes"),
                "inner": "",
                "platform": Platform.NES.value,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "hashes": RomHash(crc32="a", md5="0" * 32, sha1="1" * 40, size=stat.st_size).model_dump_json(),
            }
        ]

        assert cache.import_rows(filas) == 1
        assert cache.usable_rows() == 0, "con la ruta vieja no sirve de nada"

        assert cache.import_rows(filas, rebase=(str(vieja), str(nueva))) == 1
        assert cache.usable_rows() == 1
        assert cache.get(str(rom), None, Platform.NES, stat.st_size, stat.st_mtime_ns) is not None
    finally:
        cache.close()


def test_vaciar_la_cache_dice_cuantas_entradas_habia(tmp_path: Path) -> None:
    from retroperfect.models import RomHash
    from retroperfect.scan_cache import ScanHashCache

    cache = ScanHashCache(tmp_path / "cache.sqlite3")
    try:
        for indice in range(3):
            cache.put(f"/roms/{indice}.nes", None, Platform.NES, 10, 1, RomHash(crc32="a", md5="b", sha1="c", size=10))

        assert cache.count() == 3
        assert cache.clear() == 3
        assert cache.count() == 0
    finally:
        cache.close()
