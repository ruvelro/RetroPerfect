"""Exportación: fixdat, frontends y carátulas.

Ninguno de estos tests toca la red: la descarga de carátulas se sustituye por
un doble, igual que hacen los tests de descargas.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from retroperfect import thumbnails as thumbs
from retroperfect.dat import DatIndex, parse_dat
from retroperfect.fixdat import build_fixdat, missing_roms
from retroperfect.frontends import build_retroarch_playlist, libretro_system, write_gamelist, write_retroarch_playlist
from retroperfect.models import ActionMode, OutputBucket, Platform
from retroperfect.profile import DEFAULT_PROFILE, RECOMMENDED_PROFILES
from retroperfect.rules import build_manifest
from retroperfect.scanner import scan_directory
from test_multidisc import _dat, _escribir, _tres_discos


def _escenario(tmp_path: Path, juegos: dict, *, faltan: set[str] = frozenset(), platform: Platform = Platform.PS1):
    dat = _dat(tmp_path / "psx.xml", juegos)
    tiene = {nombre: archivos for nombre, archivos in juegos.items() if nombre not in faltan}
    roms = _escribir(tmp_path / "roms", tiene)
    catalog = parse_dat(dat)
    scan = scan_directory(roms, platform, dat_index=DatIndex(catalog), dat_path=dat)
    return catalog, scan


# --- fixdat ------------------------------------------------------------------


def test_fixdat_lista_solo_lo_que_falta(tmp_path: Path) -> None:
    catalog, scan = _escenario(tmp_path, _tres_discos("Europe"), faltan={"Final Fantasy VII (Europe) (Disc 3)"})

    faltan = missing_roms(catalog, scan)

    assert [game.name for game, _roms in faltan] == ["Final Fantasy VII (Europe) (Disc 3)"]
    xml = ET.fromstring(build_fixdat(catalog, scan, Platform.PS1))
    assert [nodo.get("name") for nodo in xml.findall("game")] == ["Final Fantasy VII (Europe) (Disc 3)"]
    assert xml.findtext("header/author") == "RetroPerfect"


def test_fixdat_de_una_coleccion_completa_sale_vacio(tmp_path: Path) -> None:
    catalog, scan = _escenario(tmp_path, _tres_discos("Europe"))

    assert missing_roms(catalog, scan) == []
    assert ET.fromstring(build_fixdat(catalog, scan, Platform.PS1)).findall("game") == []


def test_fixdat_de_un_juego_a_medias_lista_solo_las_rom_que_faltan(tmp_path: Path) -> None:
    """Un juego de Redump son varias ROMs: si te falta una pista, el fixdat pide
    esa pista, no el juego entero."""
    juegos = {"Sonic CD (Europe)": {"Sonic CD (Europe).cue": b"CUE", "Sonic CD (Europe) (Track 1).bin": b"T1", "Sonic CD (Europe) (Track 2).bin": b"T2"}}
    dat = _dat(tmp_path / "md.xml", juegos)
    parciales = {"Sonic CD (Europe)": {k: v for k, v in juegos["Sonic CD (Europe)"].items() if "Track 2" not in k}}
    roms = _escribir(tmp_path / "roms", parciales)
    catalog = parse_dat(dat)
    scan = scan_directory(roms, Platform.SEGACD, dat_index=DatIndex(catalog), dat_path=dat)

    faltan = missing_roms(catalog, scan)

    assert len(faltan) == 1
    assert [rom.name for rom in faltan[0][1]] == ["Sonic CD (Europe) (Track 2).bin"]


# --- frontends ---------------------------------------------------------------


def test_libretro_system_quita_el_prefijo_de_los_dat_no_redump() -> None:
    assert libretro_system(Platform.NES) == "Nintendo - Nintendo Entertainment System"
    assert libretro_system(Platform.PS1) == "Sony - PlayStation"  # el alias es 'Non-Redump - Sony - PlayStation'
    assert libretro_system(Platform.SATURN) == "Sega - Saturn"


def test_la_playlist_lista_el_m3u_y_no_disco_a_disco(tmp_path: Path) -> None:
    catalog, scan = _escenario(tmp_path, _tres_discos("Europe"))
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)

    playlist = build_retroarch_playlist(scan, manifest)

    assert len(playlist["items"]) == 1
    item = playlist["items"][0]
    assert item["label"] == "Final Fantasy VII"
    assert item["path"].endswith("Final Fantasy VII.m3u")
    assert item["db_name"] == "Sony - PlayStation.lpl"
    assert item["crc32"] == "00000000|crc"  # un .m3u no tiene CRC propio
    assert item["core_path"] == "DETECT"


def test_la_playlist_usa_el_nombre_del_dat_como_etiqueta(tmp_path: Path) -> None:
    """El label correcto es el del DAT: es el que casa con las carátulas."""
    juegos = {"Juego Bonito (Europe)": {"cualquier-nombre.iso": b"ROM"}}
    catalog, scan = _escenario(tmp_path, juegos)

    item = build_retroarch_playlist(scan)["items"][0]

    assert item["label"] == "Juego Bonito (Europe)"
    assert item["crc32"].endswith("|crc") and item["crc32"] != "00000000|crc"


def test_escribir_la_playlist_deja_json_valido(tmp_path: Path) -> None:
    catalog, scan = _escenario(tmp_path, {"Juego (Europe)": {"Juego (Europe).iso": b"ROM"}})

    destino = write_retroarch_playlist(scan, tmp_path / "salida.lpl")

    assert json.loads(destino.read_text(encoding="utf-8"))["items"][0]["label"] == "Juego (Europe)"


def test_el_gamelist_conserva_lo_que_ya_habia(tmp_path: Path) -> None:
    """Ahí viven los favoritos y las horas jugadas del usuario: no se pisan.

    La ROM de este escenario vive en `roms/`, así que la ruta que se escribe la
    incluye: es relativa al propio gamelist.xml, que es como la resuelve el
    frontend.
    """
    catalog, scan = _escenario(tmp_path, {"Juego (Europe)": {"Juego (Europe).iso": b"ROM"}})
    destino = tmp_path / "gamelist.xml"
    destino.write_text(
        '<?xml version="1.0"?><gameList><game><path>./Juego (Europe).iso</path>'
        "<favorite>true</favorite><playcount>42</playcount></game>"
        "<game><path>./Otro.iso</path><name>Otro juego</name></game></gameList>",
        encoding="utf-8",
    )

    write_gamelist(scan, destino)

    raiz = ET.parse(destino).getroot()
    nuestro = next(nodo for nodo in raiz.findall("game") if nodo.findtext("path") == "./roms/Juego (Europe).iso")
    assert nuestro.findtext("favorite") == "true", "se perdieron los favoritos del usuario"
    assert nuestro.findtext("playcount") == "42"
    assert nuestro.findtext("name") == "Juego (Europe)"
    assert any(nodo.findtext("path") == "./Otro.iso" for nodo in raiz.findall("game")), "se perdió una entrada ajena"


def test_un_gamelist_corrupto_se_aparta_en_vez_de_perderse(tmp_path: Path) -> None:
    catalog, scan = _escenario(tmp_path, {"Juego (Europe)": {"Juego (Europe).iso": b"ROM"}})
    destino = tmp_path / "gamelist.xml"
    destino.write_text("esto no es xml", encoding="utf-8")

    write_gamelist(scan, destino)

    assert destino.with_suffix(".xml.roto").read_text(encoding="utf-8") == "esto no es xml"
    assert ET.parse(destino).getroot().tag == "gameList"


# --- carátulas ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Super Mario Bros. (World).nes", "Super Mario Bros. (World)"),
        ("Tom & Jerry (USA).nes", "Tom _ Jerry (USA)"),
        ("Ys I & II (Japan).cue", "Ys I _ II (Japan)"),
        ("Where? (USA).nes", "Where_ (USA)"),
    ],
)
def test_nombre_de_caratula(entrada: str, esperado: str) -> None:
    assert thumbs.thumbnail_name(entrada) == esperado


def test_solo_se_piden_caratulas_de_plataformas_que_libretro_publica() -> None:
    assert thumbs.has_thumbnails(Platform.NES)
    assert thumbs.has_thumbnails(Platform.PS1)
    assert not thumbs.has_thumbnails(Platform.SWITCH)


def test_la_url_usa_el_sistema_de_libretro() -> None:
    url = thumbs.thumbnail_url(Platform.PS1, "Final Fantasy VII (Europe) (Disc 1).cue", "boxart")
    assert url == "https://thumbnails.libretro.com/Sony%20-%20PlayStation/Named_Boxarts/Final%20Fantasy%20VII%20%28Europe%29%20%28Disc%201%29.png"


class _Respuesta:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


def test_descarga_las_caratulas_de_lo_identificado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog, scan = _escenario(tmp_path, _tres_discos("Europe"))
    pedidas: list[str] = []

    def _falsa(url: str, **kwargs: object) -> _Respuesta:
        pedidas.append(url)
        return _Respuesta(200, b"PNG")

    monkeypatch.setattr(thumbs, "http_get", _falsa)
    resultados = thumbs.download_thumbnails(scan, tmp_path / "th")

    assert [r.status for r in resultados] == ["ok", "ok", "ok"]
    assert len(pedidas) == 3
    assert (tmp_path / "th" / "Named_Boxarts" / "Final Fantasy VII (Europe) (Disc 1).png").read_bytes() == b"PNG"


def test_una_caratula_que_libretro_no_tiene_se_reporta_sin_inventar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog, scan = _escenario(tmp_path, {"Juego Raro (Europe)": {"Juego Raro (Europe).iso": b"ROM"}})
    monkeypatch.setattr(thumbs, "http_get", lambda url, **kwargs: _Respuesta(404))

    resultados = thumbs.download_thumbnails(scan, tmp_path / "th")

    assert [r.status for r in resultados] == ["ausente"]
    assert not (tmp_path / "th").exists(), "no debe crear carpetas para lo que no se descargó"


def test_no_se_vuelve_a_bajar_lo_que_ya_esta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog, scan = _escenario(tmp_path, {"Juego (Europe)": {"Juego (Europe).iso": b"ROM"}})
    destino = tmp_path / "th" / "Named_Boxarts" / "Juego (Europe).png"
    destino.parent.mkdir(parents=True)
    destino.write_bytes(b"YA-ESTABA")
    monkeypatch.setattr(thumbs, "http_get", lambda url, **kwargs: _Respuesta(200, b"NUEVA"))

    resultados = thumbs.download_thumbnails(scan, tmp_path / "th")

    assert [r.status for r in resultados] == ["presente"]
    assert destino.read_bytes() == b"YA-ESTABA"


def test_el_manifiesto_acota_las_caratulas_a_lo_que_se_conserva(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    juegos = {**_tres_discos("Europe"), **_tres_discos("USA")}
    catalog, scan = _escenario(tmp_path, juegos)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)
    monkeypatch.setattr(thumbs, "http_get", lambda url, **kwargs: _Respuesta(200, b"PNG"))

    resultados = thumbs.download_thumbnails(scan, tmp_path / "th", manifest=manifest)

    assert len(resultados) == 3, "solo las tres variantes que el plan conserva"
    assert all("Europe" in Path(r.path).name for r in resultados)

def test_el_gamelist_apunta_a_la_carpeta_de_la_salida_organizada(tmp_path: Path) -> None:
    """El frontend resuelve <path> desde el propio gamelist.xml: sin la carpeta
    de la salida organizada (EUR/, USA/...) no encontraba ni un juego."""
    catalog, scan = _escenario(tmp_path, {"Juego (Europe)": {"Juego (Europe).iso": b"ROM"}})
    salida = tmp_path / "curada"
    manifest = build_manifest(scan, RECOMMENDED_PROFILES["1G1R puro"], [OutputBucket.MAIN], output_dir=salida, action=ActionMode.COPY)
    destino = salida / "gamelist.xml"

    write_gamelist(scan, destino, manifest)

    rutas = [nodo.findtext("path") for nodo in ET.parse(destino).getroot().findall("game")]
    assert rutas == ["./EUR/Juego (Europe).iso"]


def test_el_gamelist_reapunta_las_entradas_que_listaban_el_juego_en_la_raiz(tmp_path: Path) -> None:
    """Migración de los gamelist que escribió la versión con la ruta plana: se
    corrige la entrada en vez de dejar un duplicado que no apunta a nada."""
    catalog, scan = _escenario(tmp_path, {"Juego (Europe)": {"Juego (Europe).iso": b"ROM"}})
    salida = tmp_path / "curada"
    manifest = build_manifest(scan, RECOMMENDED_PROFILES["1G1R puro"], [OutputBucket.MAIN], output_dir=salida, action=ActionMode.COPY)
    destino = salida / "gamelist.xml"
    destino.parent.mkdir(parents=True)
    destino.write_text(
        '<?xml version="1.0"?><gameList><game><path>./Juego (Europe).iso</path>'
        "<favorite>true</favorite></game></gameList>",
        encoding="utf-8",
    )

    write_gamelist(scan, destino, manifest)

    juegos = ET.parse(destino).getroot().findall("game")
    assert [nodo.findtext("path") for nodo in juegos] == ["./EUR/Juego (Europe).iso"]
    assert juegos[0].findtext("favorite") == "true", "se perdieron los favoritos al migrar la ruta"

def test_el_gamelist_enlaza_la_caratula_descargada(tmp_path: Path) -> None:
    """`thumbnails` las bajaba y nadie las referenciaba, así que el frontend las
    ignoraba y acababa re-escaneando con su propia base de datos."""
    catalog, scan = _escenario(tmp_path, {"Juego (Europe)": {"Juego (Europe).iso": b"ROM"}})
    caratulas = tmp_path / "thumbnails"
    (caratulas / "Named_Boxarts").mkdir(parents=True)
    (caratulas / "Named_Boxarts" / "Juego (Europe).png").write_bytes(b"PNG")
    destino = tmp_path / "gamelist.xml"

    write_gamelist(scan, destino, None, thumbnails_dir=caratulas)

    nodo = ET.parse(destino).getroot().find("game")
    assert nodo is not None
    assert nodo.findtext("image") == "./thumbnails/Named_Boxarts/Juego (Europe).png"


def test_sin_caratula_no_se_inventa_la_etiqueta(tmp_path: Path) -> None:
    catalog, scan = _escenario(tmp_path, {"Juego (Europe)": {"Juego (Europe).iso": b"ROM"}})
    destino = tmp_path / "gamelist.xml"

    write_gamelist(scan, destino, None, thumbnails_dir=tmp_path / "thumbnails-vacias")

    assert ET.parse(destino).getroot().find("game").findtext("image") is None


def test_la_caratula_se_empareja_por_el_nombre_exacto_del_dat(tmp_path: Path) -> None:
    """Con la misma sustitución de caracteres que usa `thumbnails`: los dos
    lados tienen que normalizar igual o no se encuentra nada."""
    from retroperfect.thumbnails import thumbnail_name

    # Los dos puntos los sustituye `thumbnail_name`; `&` rompería este XML
    # de prueba, que no escapa nada (un DAT real sí lo trae como &amp;).
    juego = "Juego: Edición"
    catalog, scan = _escenario(tmp_path, {juego: {f"{juego}.iso": b"ROM"}})
    caratulas = tmp_path / "thumbnails"
    (caratulas / "Named_Snaps").mkdir(parents=True)
    (caratulas / "Named_Snaps" / f"{thumbnail_name(juego)}.png").write_bytes(b"PNG")
    destino = tmp_path / "gamelist.xml"

    write_gamelist(scan, destino, None, thumbnails_dir=caratulas)

    imagen = ET.parse(destino).getroot().find("game").findtext("image")
    assert imagen is not None and imagen.endswith(f"{thumbnail_name(juego)}.png")


# --- Pegasus -----------------------------------------------------------------


def test_pegasus_escribe_cabecera_y_un_bloque_por_juego(tmp_path: Path) -> None:
    """Pegasus es el frontend de muchas portátiles caseras y no lee ni .lpl ni
    gamelist.xml: usa un archivo de texto con su propia forma."""
    from retroperfect.frontends import write_pegasus

    catalog, scan = _escenario(tmp_path, {"Juego (Europe)": {"Juego (Europe).iso": b"ROM"}})
    destino = tmp_path / "metadata.pegasus.txt"

    write_pegasus(scan, destino)

    lineas = destino.read_text(encoding="utf-8").splitlines()
    assert lineas[0] == "collection: Sony - PlayStation"
    assert "shortname: ps1" in lineas
    assert any(linea.startswith("extensions: ") for linea in lineas)
    assert "game: Juego (Europe)" in lineas
    assert any(linea.startswith("file: ./roms/Juego (Europe).iso") for linea in lineas)
    assert "x-region: Europe" in lineas


def test_pegasus_usa_las_rutas_del_plan_y_el_m3u_de_los_multidisco(tmp_path: Path) -> None:
    from retroperfect.frontends import write_pegasus
    from test_multidisc import _tres_discos

    catalog, scan = _escenario(tmp_path, _tres_discos("Europe"))
    salida = tmp_path / "curada"
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=salida, action=ActionMode.COPY)
    destino = salida / "metadata.pegasus.txt"

    write_pegasus(scan, destino, manifest)

    texto = destino.read_text(encoding="utf-8")
    assert texto.count("game: ") == 1, "los tres discos son un solo juego en el frontend"
    assert "Final Fantasy VII.m3u" in texto


def test_pegasus_enlaza_la_caratula_si_esta(tmp_path: Path) -> None:
    from retroperfect.frontends import write_pegasus

    catalog, scan = _escenario(tmp_path, {"Juego (Europe)": {"Juego (Europe).iso": b"ROM"}})
    caratulas = tmp_path / "thumbnails"
    (caratulas / "Named_Boxarts").mkdir(parents=True)
    (caratulas / "Named_Boxarts" / "Juego (Europe).png").write_bytes(b"PNG")
    destino = tmp_path / "metadata.pegasus.txt"

    write_pegasus(scan, destino, None, thumbnails_dir=caratulas)

    assert "assets.boxFront: ./thumbnails/Named_Boxarts/Juego (Europe).png" in destino.read_text(encoding="utf-8")


def test_pegasus_se_reescribe_entero(tmp_path: Path) -> None:
    """Al contrario que el gamelist: Pegasus guarda aparte los favoritos."""
    from retroperfect.frontends import write_pegasus

    catalog, scan = _escenario(tmp_path, {"Juego (Europe)": {"Juego (Europe).iso": b"ROM"}})
    destino = tmp_path / "metadata.pegasus.txt"
    destino.write_text("basura anterior\n", encoding="utf-8")

    write_pegasus(scan, destino)

    assert "basura anterior" not in destino.read_text(encoding="utf-8")
