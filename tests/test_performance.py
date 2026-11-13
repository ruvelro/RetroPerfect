"""Candados de rendimiento, medidos en trabajo y no en tiempo.

Un umbral de reloj aquí sería inestable: esta suite varía de 12 s a 70 s entre
ejecuciones sin que cambie el código. Lo que sí es determinista es *cuánto
trabajo* se hace —consultas, extracciones, expresiones regulares, bytes— y es
justo lo que arreglaron las optimizaciones que estos tests protegen. Si un
cambio vuelve a una consulta por ROM o a extraer un 7z entero de golpe, falla
aquí en vez de aparecer como "la aplicación va lenta" meses después.
"""
from __future__ import annotations

import binascii
import hashlib
import re
from pathlib import Path

from retroperfect.dat import DatIndex, parse_dat
from retroperfect.models import ActionMode, OutputBucket, Platform, ProfileOutput, SelectionProfile
from retroperfect.scanner import scan_directory
from retroperfect.storage import save_scan

JUEGOS = 200


def _dat_grande(path: Path, juegos: int = JUEGOS, etiqueta: str = "") -> Path:
    lineas = ['<?xml version="1.0"?>', "<datafile>", "<header><name>Grande</name></header>"]
    for indice in range(juegos):
        nombre = f"Juego {indice} (Europe){etiqueta}"
        lineas.append(
            f'<game name="{nombre}"><description>{nombre}</description>'
            f'<rom name="{nombre}.nes" size="16" crc="{indice:08x}" md5="{indice:032x}" sha1="{indice:040x}"/></game>'
        )
    lineas.append("</datafile>")
    path.write_text("\n".join(lineas), encoding="utf-8")
    return path


def test_leer_un_dat_no_prueba_las_etiquetas_una_por_una(tmp_path: Path, monkeypatch) -> None:
    """El bucle de 28 TAG_KEYWORDS por cada token de cada nombre dominaba la
    carga de un DAT: 672.000 `re.escape` para 8.000 juegos. El filtro previo lo
    salta cuando el nombre no lleva ninguna etiqueta, que es lo normal."""
    from retroperfect import metadata as metadata_module

    busquedas = 0
    original = re.search

    def contar(*args, **kwargs):
        nonlocal busquedas
        busquedas += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(metadata_module.re, "search", contar)
    parse_dat(_dat_grande(tmp_path / "grande.xml"))

    # Sin el filtro previo serían al menos 28 por token y nombre (>5.600).
    assert busquedas < JUEGOS * 4, f"{busquedas} búsquedas para {JUEGOS} juegos: el filtro previo no está actuando"


def test_leer_un_dat_no_reparsea_el_mismo_nombre_tres_veces(tmp_path: Path, monkeypatch) -> None:
    """La descripción, el nombre y el de la ROM suelen ser el mismo texto."""
    from retroperfect import dat as dat_module

    parseos = 0
    original = dat_module.parse_no_intro_name

    def contar(nombre: str):
        nonlocal parseos
        parseos += 1
        return original(nombre)

    monkeypatch.setattr(dat_module, "parse_no_intro_name", contar)
    parse_dat(_dat_grande(tmp_path / "grande.xml"))

    assert parseos <= JUEGOS * 2, f"{parseos} parseos para {JUEGOS} juegos: se está repitiendo el mismo nombre"


def test_anotar_ra_no_consulta_una_vez_por_rom(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import ra as ra_module

    conn = ra_module.init_cache(tmp_path / "ra.sqlite3")
    with conn:
        for indice in range(20):
            conn.execute(
                "INSERT INTO ra_hashes(platform, hash, game_id, title) VALUES (?, ?, ?, ?)",
                # Los ids de RetroAchievements empiezan en 1; el 0 se leería como "sin RA".
                (Platform.NES.value, hashlib.md5(f"ROM{indice}".encode()).hexdigest(), indice + 1, f"Juego {indice}"),
            )
    conn.close()
    for indice in range(20):
        (tmp_path / f"Juego {indice} (Europe).nes").write_bytes(f"ROM{indice}".encode())
    scan = scan_directory(tmp_path, Platform.NES)

    consultas: list[str] = []
    original_cache = ra_module.init_cache

    def cache_rastreada(path=None):
        conexion = original_cache(path)
        conexion.set_trace_callback(lambda sql: consultas.append(sql) if "ra_hashes" in sql else None)
        return conexion

    monkeypatch.setattr(ra_module, "init_cache", cache_rastreada)
    anotado = ra_module.annotate_scan_with_ra(scan, tmp_path / "ra.sqlite3")

    assert sum(1 for rom in anotado.roms if rom.ra_game_id) == 20
    assert len(consultas) == 1, f"{len(consultas)} consultas para {len(scan.roms)} ROMs"


def test_curar_lee_los_parches_ra_una_vez_y_no_por_grupo(tmp_path: Path, monkeypatch) -> None:
    """`find_ra_patch_candidates` leía la tabla entera por cada grupo del DAT."""
    from retroperfect import ra as ra_module
    from retroperfect import rules as rules_module

    for indice in range(12):
        (tmp_path / f"Juego {indice} (Europe).nes").write_bytes(f"ROM{indice}".encode())
    scan = scan_directory(tmp_path, Platform.NES)
    lecturas = 0
    original = rules_module.ra_patch_index

    def contar(platform, cache=None):
        nonlocal lecturas
        lecturas += 1
        return original(platform, cache)

    monkeypatch.setattr(rules_module, "ra_patch_index", contar)
    monkeypatch.setattr(ra_module, "cache_path", lambda: tmp_path / "ra.sqlite3")
    profile = SelectionProfile(
        auto_patch_ra=True,
        outputs=[ProfileOutput(bucket=OutputBucket.RA, require_ra=True)],
    )

    rules_module.build_manifest(scan, profile, [OutputBucket.RA], output_dir=tmp_path / "out", action=ActionMode.COPY)

    assert lecturas <= 1, f"{lecturas} lecturas de la tabla de parches para {len(scan.roms)} grupos"


def test_el_escaneo_guardado_no_repite_la_entrada_del_dat_por_rom(tmp_path: Path) -> None:
    """Cada ROM llevaba dentro el juego del DAT con TODAS sus ROMs: un juego de
    varias pistas lo repetía una vez por pista."""
    pistas = 12
    dat = tmp_path / "psx.xml"
    roms = {f"Juego (Europe) (Track {indice}).bin": f"PISTA{indice}".encode() for indice in range(1, pistas + 1)}
    lineas = ['<?xml version="1.0"?>', "<datafile>", "<header><name>Redump</name></header>", '<game name="Juego (Europe)"><description>Juego (Europe)</description>']
    for nombre, data in roms.items():
        lineas.append(f'<rom name="{nombre}" size="{len(data)}" crc="{binascii.crc32(data) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(data).hexdigest()}" sha1="{hashlib.sha1(data).hexdigest()}"/>')
    lineas.extend(["</game>", "</datafile>"])
    dat.write_text("\n".join(lineas), encoding="utf-8")
    carpeta = tmp_path / "roms"
    carpeta.mkdir()
    for nombre, data in roms.items():
        (carpeta / nombre).write_bytes(data)

    catalog = parse_dat(dat)
    scan = scan_directory(carpeta, Platform.PS1, dat_index=DatIndex(catalog), dat_path=dat)
    guardado = save_scan(scan, state_dir=tmp_path / "estado")

    ingenuo = len(scan.model_dump_json(indent=2))
    assert guardado.stat().st_size * 2 < ingenuo, f"{guardado.stat().st_size} bytes frente a {ingenuo} sin deduplicar"
