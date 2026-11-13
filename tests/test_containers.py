"""Curar dentro de los contenedores: extraer y reempaquetar por juego.

Era el techo del proyecto: `apply` copiaba el contenedor entero, así que un ZIP
con el juego elegido y dos descartes viajaba completo, y no había forma de
escribir un ZIP nuevo con solo lo que se conserva.
"""
from __future__ import annotations

import binascii
import hashlib
import zipfile
from pathlib import Path

import pytest

from retroperfect.dat import DatIndex, parse_dat
from retroperfect.manifest_io import apply_manifest, preflight_manifest
from retroperfect.models import ActionMode, ContainerMode, OutputBucket, Platform, ProfileOutput, SelectionProfile
from retroperfect.rules import build_manifest
from retroperfect.scanner import scan_directory

PERFIL = SelectionProfile(outputs=[ProfileOutput(bucket=OutputBucket.MAIN)])


def _dat(path: Path, juegos: dict[str, dict[str, bytes]]) -> Path:
    lineas = ['<?xml version="1.0"?>', "<datafile>", "<header><name>Prueba</name></header>"]
    for juego, roms in juegos.items():
        lineas.append(f'<game name="{juego}"><description>{juego}</description>')
        for nombre, data in roms.items():
            lineas.append(
                f'<rom name="{nombre}" size="{len(data)}" crc="{binascii.crc32(data) & 0xFFFFFFFF:08x}" '
                f'md5="{hashlib.md5(data).hexdigest()}" sha1="{hashlib.sha1(data).hexdigest()}"/>'
            )
        lineas.append("</game>")
    lineas.append("</datafile>")
    path.write_text("\n".join(lineas), encoding="utf-8")
    return path


def _escenario(tmp_path: Path, dat: Path, zips: dict[str, dict[str, bytes]], platform: Platform = Platform.NES):
    carpeta = tmp_path / "roms"
    carpeta.mkdir(exist_ok=True)
    for nombre, entradas in zips.items():
        with zipfile.ZipFile(carpeta / nombre, "w") as zf:
            for interno, data in entradas.items():
                zf.writestr(interno, data)
    return scan_directory(carpeta, platform, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)


def _plan(scan, tmp_path: Path, modo: ContainerMode, profile: SelectionProfile = PERFIL):
    return build_manifest(scan, profile, [OutputBucket.MAIN], output_dir=tmp_path / "out", action=ActionMode.COPY, container_mode=modo)


def test_por_defecto_se_sigue_copiando_el_contenedor_entero(tmp_path: Path) -> None:
    """El comportamiento de siempre no cambia si no se pide otra cosa."""
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    scan = _escenario(tmp_path, dat, {"set.zip": {"Juego (Europe).nes": b"EU"}})

    manifest = _plan(scan, tmp_path, ContainerMode.KEEP)

    assert manifest.archives == []
    assert [Path(entry.destination_path or "").name for entry in manifest.entries] == ["set.zip"]
    apply_manifest(manifest, confirm=True)
    assert (tmp_path / "out" / "main" / "set.zip").exists()


def test_extraer_deja_la_rom_suelta_y_con_el_nombre_del_dat(tmp_path: Path) -> None:
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    scan = _escenario(tmp_path, dat, {"set.zip": {"mal_nombrada.nes": b"EU"}})

    manifest = _plan(scan, tmp_path, ContainerMode.EXTRACT)
    completed = apply_manifest(manifest, confirm=True)

    destino = tmp_path / "out" / "main" / "Juego (Europe).nes"
    assert destino.read_bytes() == b"EU"
    assert not (tmp_path / "out" / "main" / "set.zip").exists(), "el contenedor no debe viajar"
    assert any("extraído" in linea and "md5 verificado" in linea for linea in completed)


def test_extraer_solo_saca_lo_que_el_plan_conserva(tmp_path: Path) -> None:
    """Es el agujero que cerraba esto: antes los descartes viajaban dentro."""
    dat = _dat(
        tmp_path / "nes.xml",
        {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}, "Juego (USA)": {"Juego (USA).nes": b"US"}},
    )
    scan = _escenario(tmp_path, dat, {"set.zip": {"Juego (Europe).nes": b"EU", "Juego (USA).nes": b"US"}})

    apply_manifest(_plan(scan, tmp_path, ContainerMode.EXTRACT), confirm=True)

    salida = sorted(item.name for item in (tmp_path / "out" / "main").iterdir())
    assert salida == ["Juego (Europe).nes"], salida


def test_reempaquetar_escribe_un_zip_por_juego(tmp_path: Path) -> None:
    dat = _dat(
        tmp_path / "nes.xml",
        {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}, "Juego (USA)": {"Juego (USA).nes": b"US"}},
    )
    scan = _escenario(tmp_path, dat, {"set.zip": {"Juego (Europe).nes": b"EU", "Juego (USA).nes": b"US"}})

    manifest = _plan(scan, tmp_path, ContainerMode.REZIP)
    completed = apply_manifest(manifest, confirm=True)

    destino = tmp_path / "out" / "main" / "Juego (Europe).zip"
    assert destino.exists()
    with zipfile.ZipFile(destino) as zf:
        assert zf.namelist() == ["Juego (Europe).nes"], "el descarte no puede colarse dentro"
        assert zf.read("Juego (Europe).nes") == b"EU"
    assert any("empaquetado" in linea and "verificado" in linea for linea in completed)


def test_reempaquetar_junta_todas_las_piezas_de_un_juego(tmp_path: Path) -> None:
    """Un juego de Redump son varios archivos y van al mismo ZIP."""
    pistas = {"Juego (Europe).cue": b"CUE", "Juego (Europe) (Track 1).bin": b"T1", "Juego (Europe) (Track 2).bin": b"T2"}
    dat = _dat(tmp_path / "psx.xml", {"Juego (Europe)": pistas})
    scan = _escenario(tmp_path, dat, {"juego.zip": pistas}, platform=Platform.PS1)

    manifest = _plan(scan, tmp_path, ContainerMode.REZIP)
    apply_manifest(manifest, confirm=True)

    assert len(manifest.archives) == 1
    with zipfile.ZipFile(tmp_path / "out" / "main" / "Juego (Europe).zip") as zf:
        assert sorted(zf.namelist()) == sorted(pistas)


def test_reempaquetar_usa_los_nombres_del_dat_dentro_del_zip(tmp_path: Path) -> None:
    """Es lo que hace que dos colecciones curadas con el mismo DAT salgan iguales."""
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    scan = _escenario(tmp_path, dat, {"set.zip": {"basura_v2_final.nes": b"EU"}})

    apply_manifest(_plan(scan, tmp_path, ContainerMode.REZIP), confirm=True)

    with zipfile.ZipFile(tmp_path / "out" / "main" / "Juego (Europe).zip") as zf:
        assert zf.namelist() == ["Juego (Europe).nes"]


def test_reempaquetar_tambien_vale_para_archivos_sueltos(tmp_path: Path) -> None:
    """Comprimir una colección suelta es el mismo trabajo al revés."""
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    carpeta = tmp_path / "roms"
    carpeta.mkdir()
    (carpeta / "Juego (Europe).nes").write_bytes(b"EU")
    scan = scan_directory(carpeta, Platform.NES, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)

    apply_manifest(_plan(scan, tmp_path, ContainerMode.REZIP), confirm=True)

    with zipfile.ZipFile(tmp_path / "out" / "main" / "Juego (Europe).zip") as zf:
        assert zf.read("Juego (Europe).nes") == b"EU"


def test_varias_entradas_al_mismo_zip_no_son_una_colision(tmp_path: Path) -> None:
    """Comparten destino a propósito: es el ZIP del juego."""
    pistas = {"Juego (Europe).cue": b"CUE", "Juego (Europe) (Track 1).bin": b"T1"}
    dat = _dat(tmp_path / "psx.xml", {"Juego (Europe)": pistas})
    scan = _escenario(tmp_path, dat, {"juego.zip": pistas}, platform=Platform.PS1)

    assert preflight_manifest(_plan(scan, tmp_path, ContainerMode.REZIP)) == []


def test_el_preflight_cuenta_el_tamano_de_la_rom_no_del_contenedor(tmp_path: Path, monkeypatch) -> None:
    """Un ZIP de 4 GB del que se saca una ROM de 2 MB sí cabe."""
    import shutil as shutil_module

    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU" * 10}})
    scan = _escenario(tmp_path, dat, {"set.zip": {"Juego (Europe).nes": b"EU" * 10}})
    contenedor = (tmp_path / "roms" / "set.zip").stat().st_size
    # Espacio justo para la ROM, no para el contenedor.
    monkeypatch.setattr(shutil_module, "disk_usage", lambda _path: shutil_module._ntuple_diskusage(contenedor, contenedor - 25, 25))

    assert preflight_manifest(_plan(scan, tmp_path, ContainerMode.EXTRACT)) == []
    assert any("Espacio insuficiente" in issue for issue in preflight_manifest(_plan(scan, tmp_path, ContainerMode.KEEP)))


def test_un_zip_de_destino_con_otro_contenido_no_se_pisa(tmp_path: Path) -> None:
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    scan = _escenario(tmp_path, dat, {"set.zip": {"Juego (Europe).nes": b"EU"}})
    manifest = _plan(scan, tmp_path, ContainerMode.REZIP)
    destino = tmp_path / "out" / "main" / "Juego (Europe).zip"
    destino.parent.mkdir(parents=True)
    destino.write_bytes(b"ESTO ES MIO Y NO ES UN ZIP")

    with pytest.raises(RuntimeError, match="no contiene lo planificado"):
        apply_manifest(manifest, confirm=True)
    assert destino.read_bytes() == b"ESTO ES MIO Y NO ES UN ZIP"

    apply_manifest(manifest, confirm=True, overwrite=True)
    with zipfile.ZipFile(destino) as zf:
        assert zf.namelist() == ["Juego (Europe).nes"]


def test_aplicar_dos_veces_no_rehace_los_zip(tmp_path: Path) -> None:
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    scan = _escenario(tmp_path, dat, {"set.zip": {"Juego (Europe).nes": b"EU"}})
    manifest = _plan(scan, tmp_path, ContainerMode.REZIP)

    apply_manifest(manifest, confirm=True)
    segunda = apply_manifest(manifest, confirm=True)

    assert any("ya contenía" in linea for linea in segunda)


def test_un_contenedor_que_cambio_desde_el_escaneo_no_entra_en_el_zip(tmp_path: Path) -> None:
    """Verificar el ZIP por su propio hash no diría nada: lo que importa es que
    dentro esté lo que el plan dijo."""
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    scan = _escenario(tmp_path, dat, {"set.zip": {"Juego (Europe).nes": b"EU"}})
    manifest = _plan(scan, tmp_path, ContainerMode.REZIP)
    with zipfile.ZipFile(tmp_path / "roms" / "set.zip", "w") as zf:
        zf.writestr("Juego (Europe).nes", b"OTRA COSA")

    with pytest.raises(RuntimeError, match="cambió desde el escaneo"):
        apply_manifest(manifest, confirm=True)
    assert not (tmp_path / "out" / "main" / "Juego (Europe).zip").exists(), "no puede quedar un ZIP a medias"


def test_una_rom_que_cambio_dentro_del_zip_no_se_extrae(tmp_path: Path) -> None:
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    scan = _escenario(tmp_path, dat, {"set.zip": {"Juego (Europe).nes": b"EU"}})
    manifest = _plan(scan, tmp_path, ContainerMode.EXTRACT)
    with zipfile.ZipFile(tmp_path / "roms" / "set.zip", "w") as zf:
        zf.writestr("Juego (Europe).nes", b"OTRA COSA")

    with pytest.raises(RuntimeError, match="cambió desde el escaneo"):
        apply_manifest(manifest, confirm=True)


def test_deshacer_borra_los_zip_que_escribio_el_plan(tmp_path: Path) -> None:
    from retroperfect.undoing import apply_undo, latest_journal, plan_undo

    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    scan = _escenario(tmp_path, dat, {"set.zip": {"Juego (Europe).nes": b"EU"}})
    manifest = _plan(scan, tmp_path, ContainerMode.REZIP)
    apply_manifest(manifest, confirm=True, journal_dir=tmp_path / "applied")
    destino = tmp_path / "out" / "main" / "Juego (Europe).zip"
    assert destino.exists()

    journal = latest_journal(tmp_path / "applied")
    assert journal is not None
    apply_undo(plan_undo(journal))

    assert not destino.exists()


def test_extraer_dos_veces_reconoce_lo_ya_hecho(tmp_path: Path) -> None:
    """Comparar el destino con el MD5 del ZIP nunca casaría: una extracción ya
    aplicada se habría tomado por un archivo ajeno."""
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    scan = _escenario(tmp_path, dat, {"set.zip": {"Juego (Europe).nes": b"EU"}})
    manifest = _plan(scan, tmp_path, ContainerMode.EXTRACT)

    apply_manifest(manifest, confirm=True)
    segunda = apply_manifest(manifest, confirm=True)

    assert any("ya estaba aplicado" in linea for linea in segunda)


def test_extraer_no_pisa_un_archivo_ajeno_del_destino(tmp_path: Path) -> None:
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    scan = _escenario(tmp_path, dat, {"set.zip": {"Juego (Europe).nes": b"EU"}})
    manifest = _plan(scan, tmp_path, ContainerMode.EXTRACT)
    destino = tmp_path / "out" / "main" / "Juego (Europe).nes"
    destino.parent.mkdir(parents=True)
    destino.write_bytes(b"MIO")

    with pytest.raises(RuntimeError, match="El destino ya existe|ya existe con otro contenido"):
        apply_manifest(manifest, confirm=True)
    assert destino.read_bytes() == b"MIO"


# --- TorrentZip --------------------------------------------------------------


def test_un_zip_canonico_sale_igual_dos_veces(tmp_path: Path) -> None:
    """Es la razón de ser del formato: el mismo contenido, los mismos bytes, así
    que la colección se puede verificar o compartir por hash del contenedor."""
    from retroperfect.torrentzip import write_torrentzip

    miembros = [("b.nes", b"BBB"), ("a.nes", b"AAA")]
    primero = tmp_path / "uno.zip"
    segundo = tmp_path / "dos.zip"

    write_torrentzip(primero, miembros)
    write_torrentzip(segundo, list(reversed(miembros)))

    assert primero.read_bytes() == segundo.read_bytes(), "el orden de entrada no puede cambiar el archivo"


def test_un_zip_canonico_ordena_y_fija_la_fecha(tmp_path: Path) -> None:
    from retroperfect.torrentzip import TORRENTZIP_DATE, write_torrentzip

    destino = tmp_path / "set.zip"
    write_torrentzip(destino, [("Zelda.nes", b"Z"), ("metroid.nes", b"M"), ("Contra.nes", b"C")])

    with zipfile.ZipFile(destino) as zf:
        assert zf.namelist() == ["Contra.nes", "metroid.nes", "Zelda.nes"], "orden por nombre en minúsculas"
        assert {info.date_time for info in zf.infolist()} == {TORRENTZIP_DATE}


def test_la_firma_del_zip_canonico_cuadra_con_su_contenido(tmp_path: Path) -> None:
    from retroperfect.torrentzip import is_torrentzipped, signature, write_torrentzip

    destino = tmp_path / "set.zip"
    write_torrentzip(destino, [("a.nes", b"AAA")])

    firma = signature(destino)
    assert firma is not None and firma.startswith("TORRENTZIPPED-")
    assert is_torrentzipped(destino)


def test_un_zip_normal_no_se_hace_pasar_por_canonico(tmp_path: Path) -> None:
    from retroperfect.torrentzip import is_torrentzipped, signature

    destino = tmp_path / "normal.zip"
    with zipfile.ZipFile(destino, "w") as zf:
        zf.writestr("a.nes", b"AAA")

    assert signature(destino) is None
    assert not is_torrentzipped(destino)


def test_una_firma_que_ya_no_corresponde_se_detecta(tmp_path: Path) -> None:
    """Una firma que no cuadra es peor que ninguna: invita a confiar en un
    archivo que ha cambiado."""
    from retroperfect.torrentzip import is_torrentzipped, write_torrentzip

    destino = tmp_path / "set.zip"
    write_torrentzip(destino, [("a.nes", b"AAA")])
    datos = bytearray(destino.read_bytes())
    datos[-1:] = b"0" if datos[-1:] != b"0" else b"1"
    destino.write_bytes(bytes(datos))

    assert not is_torrentzipped(destino)


def test_el_plan_con_torrentzip_escribe_un_zip_canonico(tmp_path: Path) -> None:
    from retroperfect.torrentzip import is_torrentzipped

    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    scan = _escenario(tmp_path, dat, {"set.zip": {"basura.nes": b"EU"}})

    completed = apply_manifest(_plan(scan, tmp_path, ContainerMode.TORRENTZIP), confirm=True)

    destino = tmp_path / "out" / "main" / "Juego (Europe).zip"
    assert is_torrentzipped(destino)
    with zipfile.ZipFile(destino) as zf:
        assert zf.namelist() == ["Juego (Europe).nes"]
    assert any("canónico" in linea for linea in completed)


def test_dos_colecciones_iguales_dan_el_mismo_zip(tmp_path: Path) -> None:
    """El caso que da sentido al formato: dos personas, el mismo juego, el mismo
    DAT, nombres de archivo distintos de partida."""
    from retroperfect.torrentzip import is_torrentzipped

    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"EU"}})
    resultados = []
    for indice, interno in enumerate(["basura_v1.nes", "JUEGO-EUR.nes"]):
        suyo = tmp_path / f"coleccion{indice}"
        suyo.mkdir()
        with zipfile.ZipFile(suyo / "set.zip", "w") as zf:
            zf.writestr(interno, b"EU")
        scan = scan_directory(suyo, Platform.NES, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
        manifest = build_manifest(scan, PERFIL, [OutputBucket.MAIN], output_dir=suyo / "out", action=ActionMode.COPY, container_mode=ContainerMode.TORRENTZIP)
        apply_manifest(manifest, confirm=True)
        destino = suyo / "out" / "main" / "Juego (Europe).zip"
        assert is_torrentzipped(destino)
        resultados.append(destino.read_bytes())

    assert resultados[0] == resultados[1], "mismo contenido y mismo DAT tienen que dar el mismo archivo"
