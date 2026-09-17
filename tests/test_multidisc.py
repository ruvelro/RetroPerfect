"""Juegos repartidos en varias piezas: discos y archivos.

Un juego de Redump son varios archivos (un .cue y sus .bin) y puede ocupar
varios discos. Antes el 1G1R agrupaba por el título pelado —que pierde el
"(Disc 2)"— y elegía un solo archivo por grupo, así que de un juego de tres
discos sobrevivía el primero y de un cue+bin sobrevivía un .bin sin su .cue.
Estos tests fijan las cuatro caras del arreglo: curación, cobertura,
verificación y descarga.
"""
from __future__ import annotations

import binascii
import hashlib
from pathlib import Path

import pytest

from retroperfect.coverage import build_coverage
from retroperfect.dat import DatIndex, parse_dat
from retroperfect.download_plan import build_download_plan
from retroperfect.manifest_io import apply_manifest
from retroperfect.metadata import detect_part, parse_no_intro_name
from retroperfect.models import ActionMode, OutputBucket, Platform
from retroperfect.profile import DEFAULT_PROFILE
from retroperfect.rom_sources import RemoteFile
from retroperfect.rules import build_manifest
from retroperfect.scanner import scan_directory
from retroperfect.verify import verify_collection


def _dat(path: Path, juegos: dict[str, dict[str, bytes]]) -> Path:
    """DAT Logiqx donde cada juego puede declarar varias ROMs."""
    entradas = []
    for juego, archivos in juegos.items():
        region = juego.split("(")[1].split(")")[0] if "(" in juego else "Europe"
        filas = "".join(
            f'<rom name="{nombre}" size="{len(payload)}" crc="{binascii.crc32(payload) & 0xFFFFFFFF:08x}" '
            f'md5="{hashlib.md5(payload).hexdigest()}" sha1="{hashlib.sha1(payload).hexdigest()}"/>'
            for nombre, payload in archivos.items()
        )
        entradas.append(f'<game name="{juego}"><description>{juego}</description><release name="{juego}" region="{region}"/>{filas}</game>')
    path.write_text(f"<datafile><header><name>Discos</name></header>{''.join(entradas)}</datafile>", encoding="utf-8")
    return path


def _escribir(directorio: Path, juegos: dict[str, dict[str, bytes]]) -> Path:
    directorio.mkdir(parents=True, exist_ok=True)
    for archivos in juegos.values():
        for nombre, payload in archivos.items():
            (directorio / nombre).write_bytes(payload)
    return directorio


def _tres_discos(region: str) -> dict[str, dict[str, bytes]]:
    return {f"Final Fantasy VII ({region}) (Disc {n})": {f"Final Fantasy VII ({region}) (Disc {n}).iso": f"{region}-{n}".encode()} for n in (1, 2, 3)}


def _cue_y_pistas() -> dict[str, dict[str, bytes]]:
    return {
        "Sonic CD (Europe)": {
            "Sonic CD (Europe).cue": b"FILE track01.bin",
            "Sonic CD (Europe) (Track 1).bin": b"PISTA-1-DATOS",
            "Sonic CD (Europe) (Track 2).bin": b"PISTA-2-AUDIO",
        }
    }


# --- Detección del soporte ---------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Disc 2", "disc 2"),
        ("Disk 1 of 3", "disc 1"),  # TOSEC
        ("CD 2", "disc 2"),
        ("Side A", "side a"),
        ("Tape 2", "tape 2"),
        ("Europe", None),
        ("Rev 2", None),  # una revisión no es un soporte
        ("Beta", None),
    ],
)
def test_detect_part(texto: str, esperado: str | None) -> None:
    assert detect_part(texto) == esperado


def test_el_soporte_no_se_confunde_con_la_revision() -> None:
    metadata = parse_no_intro_name("Juego (Europe) (Disc 1) (Rev A).cue")
    assert metadata.part == "disc 1"
    assert metadata.revision == 1
    assert metadata.title == "Juego"


# --- Curación ----------------------------------------------------------------


def test_conserva_los_tres_discos_del_juego(tmp_path: Path) -> None:
    juegos = _tres_discos("Europe")
    dat = _dat(tmp_path / "psx.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)

    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)

    copiados = sorted(Path(entry.source_path).name for entry in manifest.entries)
    assert copiados == [f"Final Fantasy VII (Europe) (Disc {n}).iso" for n in (1, 2, 3)]
    assert not [decision for decision in manifest.discarded if not decision.kept]


def test_el_1g1r_sigue_descartando_regiones_pero_conserva_sus_discos(tmp_path: Path) -> None:
    """La prueba de que el arreglo no convirtió el 1G1R en un 'cópialo todo'."""
    juegos = {**_tres_discos("Europe"), **_tres_discos("USA"), **_tres_discos("Japan")}
    dat = _dat(tmp_path / "psx.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)

    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)

    copiados = sorted(Path(entry.source_path).name for entry in manifest.entries)
    assert copiados == [f"Final Fantasy VII (Europe) (Disc {n}).iso" for n in (1, 2, 3)], "debe quedarse una región entera, no una mezcla"
    assert len([decision for decision in manifest.discarded if not decision.kept]) == 6  # las otras dos regiones


def test_conserva_todos_los_archivos_de_un_juego_cue_bin(tmp_path: Path) -> None:
    juegos = _cue_y_pistas()
    dat = _dat(tmp_path / "md.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)

    scan = scan_directory(roms, Platform.SEGACD, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)

    copiados = sorted(Path(entry.source_path).name for entry in manifest.entries)
    assert copiados == ["Sonic CD (Europe) (Track 1).bin", "Sonic CD (Europe) (Track 2).bin", "Sonic CD (Europe).cue"]


def test_borrar_no_manda_a_la_papelera_las_piezas_del_juego_elegido(tmp_path: Path) -> None:
    """Con acción borrar, las pistas del ganador no pueden contarse como descarte."""
    juegos = _cue_y_pistas()
    dat = _dat(tmp_path / "md.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)

    scan = scan_directory(roms, Platform.SEGACD, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.DELETE)

    assert [entry.source_path for entry in manifest.entries] == []


def test_prefiere_la_variante_completa_aunque_pierda_por_region(tmp_path: Path) -> None:
    """Europa gana por prioridad, pero solo tiene el disco 1: mezclar regiones
    deja un juego que no arranca, así que se lleva el set entero de USA."""
    todos = {**_tres_discos("Europe"), **_tres_discos("USA")}
    dat = _dat(tmp_path / "psx.xml", todos)
    tiene = {nombre: archivos for nombre, archivos in todos.items() if "USA" in nombre or nombre.endswith("(Europe) (Disc 1)")}
    roms = _escribir(tmp_path / "roms", tiene)

    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)

    copiados = sorted(Path(entry.source_path).name for entry in manifest.entries)
    assert copiados == [f"Final Fantasy VII (USA) (Disc {n}).iso" for n in (1, 2, 3)]


def test_sin_ninguna_variante_completa_no_se_pierde_nada(tmp_path: Path) -> None:
    """Si no hay ninguna región entera, se conserva lo que haya: es lo único
    jugable que tiene el usuario, y borrarlo no lo arreglaría."""
    todos = {**_tres_discos("Europe"), **_tres_discos("USA")}
    dat = _dat(tmp_path / "psx.xml", todos)
    tiene = {nombre: archivos for nombre, archivos in todos.items() if nombre.endswith("(Europe) (Disc 1)") or ("USA" in nombre and not nombre.endswith("(Disc 1)"))}
    roms = _escribir(tmp_path / "roms", tiene)

    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)

    copiados = sorted(Path(entry.source_path).name for entry in manifest.entries)
    assert copiados == ["Final Fantasy VII (Europe) (Disc 1).iso", "Final Fantasy VII (USA) (Disc 2).iso", "Final Fantasy VII (USA) (Disc 3).iso"]


# --- Cobertura y verificación ------------------------------------------------


def test_verify_avisa_del_set_mixto(tmp_path: Path) -> None:
    todos = {**_tres_discos("Europe"), **_tres_discos("USA")}
    dat = _dat(tmp_path / "psx.xml", todos)
    tiene = {nombre: archivos for nombre, archivos in todos.items() if nombre.endswith("(Europe) (Disc 1)") or ("USA" in nombre and not nombre.endswith("(Disc 1)"))}
    roms = _escribir(tmp_path / "roms", tiene)

    catalog = parse_dat(dat)
    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(catalog), dat_path=dat)
    report = verify_collection(scan, catalog)

    assert report.mixed == 1
    aviso = next(issue for issue in report.issues if issue.status == "SET MIXTO")
    # el aviso tiene que decir qué tiene de cada variante, no solo que hay un lío
    assert "Final Fantasy VII (Europe): disc 1" in aviso.detail
    assert "Final Fantasy VII (USA): disc 2, disc 3" in aviso.detail


def test_un_set_completo_no_se_marca_como_mixto(tmp_path: Path) -> None:
    """Tener las dos regiones enteras es acumular, no mezclar: no es un problema."""
    todos = {**_tres_discos("Europe"), **_tres_discos("USA")}
    dat = _dat(tmp_path / "psx.xml", todos)
    roms = _escribir(tmp_path / "roms", todos)

    catalog = parse_dat(dat)
    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(catalog), dat_path=dat)

    assert verify_collection(scan, catalog).mixed == 0


def test_la_cobertura_cuenta_cada_disco(tmp_path: Path) -> None:
    juegos = _tres_discos("Europe")
    dat = _dat(tmp_path / "psx.xml", juegos)
    solo_uno = _escribir(tmp_path / "solo1", {"Final Fantasy VII (Europe) (Disc 1)": juegos["Final Fantasy VII (Europe) (Disc 1)"]})

    catalog = parse_dat(dat)
    scan = scan_directory(solo_uno, Platform.PS1, dat_index=DatIndex(catalog), dat_path=dat)
    summary = build_coverage(scan, catalog)

    assert summary.dat_games == 3
    assert summary.missing_from_romset == 2


def test_verify_dice_que_discos_faltan(tmp_path: Path) -> None:
    juegos = _tres_discos("Europe")
    dat = _dat(tmp_path / "psx.xml", juegos)
    solo_uno = _escribir(tmp_path / "solo1", {"Final Fantasy VII (Europe) (Disc 1)": juegos["Final Fantasy VII (Europe) (Disc 1)"]})

    catalog = parse_dat(dat)
    scan = scan_directory(solo_uno, Platform.PS1, dat_index=DatIndex(catalog), dat_path=dat)
    report = verify_collection(scan, catalog)

    assert report.missing == 2
    faltantes = sorted(issue.title for issue in report.issues if issue.status == "FALTA")
    assert faltantes == ["Final Fantasy VII · disc 2", "Final Fantasy VII · disc 3"]


def test_verify_no_acusa_de_mal_nombrado_a_las_pistas(tmp_path: Path) -> None:
    """Antes decía que los tres archivos debían llamarse todos como el .cue,
    un consejo que habría destruido el juego."""
    juegos = _cue_y_pistas()
    dat = _dat(tmp_path / "md.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)

    catalog = parse_dat(dat)
    scan = scan_directory(roms, Platform.SEGACD, dat_index=DatIndex(catalog), dat_path=dat)
    report = verify_collection(scan, catalog)

    assert report.misnamed == 0, [issue.detail for issue in report.issues]
    assert report.clean


# --- Playlists ---------------------------------------------------------------


def test_genera_un_m3u_con_los_discos_en_orden(tmp_path: Path) -> None:
    """Los emuladores guardan la partida contra el nombre del .m3u: sin él cada
    disco tiene su propio save y el juego no se puede terminar."""
    juegos = _tres_discos("Europe")
    dat = _dat(tmp_path / "psx.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)

    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)

    assert len(manifest.playlists) == 1
    playlist = manifest.playlists[0]
    assert playlist.title == "Final Fantasy VII"
    assert playlist.entries == [f"Final Fantasy VII (Europe) (Disc {n}).iso" for n in (1, 2, 3)]
    assert Path(playlist.path).name == "Final Fantasy VII.m3u"


def test_un_juego_de_un_solo_disco_no_genera_playlist(tmp_path: Path) -> None:
    juegos = {"Juego (Europe)": {"Juego (Europe).iso": b"UNO"}}
    dat = _dat(tmp_path / "psx.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)

    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)

    assert manifest.playlists == []


def test_el_disco_10_va_despues_del_2(tmp_path: Path) -> None:
    """Ordenar los soportes como texto pondría el 10 antes del 2."""
    juegos = {f"Saga ({'Europe'}) (Disc {n})": {f"Saga (Europe) (Disc {n}).iso": f"D{n}".encode()} for n in (1, 2, 10)}
    dat = _dat(tmp_path / "psx.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)

    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)

    assert manifest.playlists[0].entries == ["Saga (Europe) (Disc 1).iso", "Saga (Europe) (Disc 2).iso", "Saga (Europe) (Disc 10).iso"]


def test_aplicar_escribe_el_m3u_junto_a_los_discos(tmp_path: Path) -> None:
    juegos = _tres_discos("Europe")
    dat = _dat(tmp_path / "psx.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)
    salida = tmp_path / "out"

    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=salida, action=ActionMode.COPY)
    apply_manifest(manifest, confirm=True, journal_dir=tmp_path / "journal")

    m3u = salida / "main" / "Final Fantasy VII.m3u"
    assert m3u.read_text(encoding="utf-8").splitlines() == [f"Final Fantasy VII (Europe) (Disc {n}).iso" for n in (1, 2, 3)]


def test_borrar_no_genera_playlists(tmp_path: Path) -> None:
    juegos = _tres_discos("Europe")
    dat = _dat(tmp_path / "psx.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)

    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.DELETE)

    assert manifest.playlists == []


# --- Enlaces duros -----------------------------------------------------------


def test_link_no_duplica_el_espacio(tmp_path: Path) -> None:
    """El enlace duro comparte inodo: la colección curada no ocupa el doble."""
    juegos = {"Juego (Europe)": {"Juego (Europe).iso": b"CONTENIDO"}}
    dat = _dat(tmp_path / "psx.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)
    salida = tmp_path / "out"

    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=salida, action=ActionMode.COPY)
    completado = apply_manifest(manifest, confirm=True, link=True, journal_dir=tmp_path / "journal")

    origen = roms / "Juego (Europe).iso"
    destino = salida / "main" / "Juego (Europe).iso"
    assert destino.stat().st_ino == origen.stat().st_ino
    assert any("enlace duro" in linea for linea in completado)


def test_sin_link_se_copia_de_verdad(tmp_path: Path) -> None:
    juegos = {"Juego (Europe)": {"Juego (Europe).iso": b"CONTENIDO"}}
    dat = _dat(tmp_path / "psx.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)
    salida = tmp_path / "out"

    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=salida, action=ActionMode.COPY)
    apply_manifest(manifest, confirm=True, journal_dir=tmp_path / "journal")

    origen = roms / "Juego (Europe).iso"
    destino = salida / "main" / "Juego (Europe).iso"
    assert destino.stat().st_ino != origen.stat().st_ino
    assert destino.read_bytes() == origen.read_bytes()


def test_link_detecta_que_el_origen_cambio_desde_el_escaneo(tmp_path: Path) -> None:
    """Enlazar no copia nada, pero la comprobación de que el origen sigue siendo
    el que se escaneó no puede perderse por el camino."""
    juegos = {"Juego (Europe)": {"Juego (Europe).iso": b"CONTENIDO"}}
    dat = _dat(tmp_path / "psx.xml", juegos)
    roms = _escribir(tmp_path / "roms", juegos)

    scan = scan_directory(roms, Platform.PS1, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, DEFAULT_PROFILE, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY)
    (roms / "Juego (Europe).iso").write_bytes(b"OTRA-COSA")

    with pytest.raises(RuntimeError, match="cambió"):
        apply_manifest(manifest, confirm=True, link=True, journal_dir=tmp_path / "journal")


# --- Descarga ----------------------------------------------------------------


def test_el_plan_de_descarga_ofrece_los_discos_que_faltan(tmp_path: Path) -> None:
    juegos = _tres_discos("Europe")
    dat = _dat(tmp_path / "psx.xml", juegos)
    solo_uno = _escribir(tmp_path / "solo1", {"Final Fantasy VII (Europe) (Disc 1)": juegos["Final Fantasy VII (Europe) (Disc 1)"]})

    catalog = parse_dat(dat)
    scan = scan_directory(solo_uno, Platform.PS1, dat_index=DatIndex(catalog), dat_path=dat)
    remotos = {
        "espejo": [
            RemoteFile(name=f"Final Fantasy VII (Europe) (Disc {n}).iso", url=f"file:///espejo/disc{n}.iso", size=7)
            for n in (1, 2, 3)
        ]
    }
    plan = build_download_plan(catalog, scan, DEFAULT_PROFILE, remotos, platform=Platform.PS1)

    ofrecidos = sorted(candidate.file_name for candidate in plan.candidates)
    assert ofrecidos == [f"Final Fantasy VII (Europe) (Disc {n}).iso" for n in (2, 3)]
    assert plan.dat_groups == 3
    assert plan.present_groups == 1
