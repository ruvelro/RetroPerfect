"""Renombrado en el sitio contra el nombre que dice el DAT.

`verify` detectaba los mal nombrados y no había forma de arreglarlos salvo
planificar una copia entera de la colección.
"""
from __future__ import annotations

import binascii
import hashlib
from pathlib import Path

from retroperfect.dat import DatIndex, parse_dat
from retroperfect.models import Platform
from retroperfect.renaming import apply_renames, expected_file_name, plan_renames
from retroperfect.scanner import scan_directory


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


def _escanear(tmp_path: Path, dat: Path, archivos: dict[str, bytes], platform: Platform = Platform.NES):
    carpeta = tmp_path / "roms"
    carpeta.mkdir(exist_ok=True)
    for nombre, data in archivos.items():
        (carpeta / nombre).write_bytes(data)
    return carpeta, scan_directory(carpeta, platform, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)


def test_un_archivo_mal_nombrado_se_planifica_con_el_nombre_del_dat(tmp_path: Path) -> None:
    payload = b"ROM"
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": payload}})
    carpeta, scan = _escanear(tmp_path, dat, {"juego_eur_hack.nes": payload})

    planes = plan_renames(scan)

    assert len(planes) == 1
    assert planes[0].current_name == "juego_eur_hack.nes"
    assert planes[0].expected_name == "Juego (Europe).nes"
    assert planes[0].can_apply
    assert apply_renames(planes) == ["renombrado juego_eur_hack.nes -> Juego (Europe).nes"]
    assert (carpeta / "Juego (Europe).nes").read_bytes() == payload
    assert not (carpeta / "juego_eur_hack.nes").exists()


def test_los_archivos_bien_nombrados_no_salen_en_el_plan(tmp_path: Path) -> None:
    payload = b"ROM"
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": payload}})
    _carpeta, scan = _escanear(tmp_path, dat, {"Juego (Europe).nes": payload})

    assert plan_renames(scan) == []


def test_un_archivo_fuera_del_dat_se_deja_en_paz(tmp_path: Path) -> None:
    """Sin coincidencia no hay nombre correcto que imponer."""
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": b"ROM"}})
    _carpeta, scan = _escanear(tmp_path, dat, {"Juego (Europe).nes": b"ROM", "raro.nes": b"OTRO"})

    assert [plan.current_name for plan in plan_renames(scan)] == []


def test_cada_pista_de_un_juego_recibe_su_propio_nombre(tmp_path: Path) -> None:
    """Un juego de Redump son varias ROMs: dar por hecho que es la primera
    aconsejaba renombrarlas todas igual, lo que destruiría el juego."""
    pistas = {"Juego (Europe).cue": b"CUE", "Juego (Europe) (Track 1).bin": b"T1", "Juego (Europe) (Track 2).bin": b"T2"}
    dat = _dat(tmp_path / "psx.xml", {"Juego (Europe)": pistas})
    carpeta, scan = _escanear(tmp_path, dat, {"a.cue": b"CUE", "b.bin": b"T1", "c.bin": b"T2"}, platform=Platform.PS1)

    apply_renames(plan_renames(scan))

    assert sorted(item.name for item in carpeta.iterdir()) == sorted(pistas)


def test_no_se_sobrescribe_un_archivo_que_ya_existe(tmp_path: Path) -> None:
    payload = b"ROM"
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": payload}})
    carpeta, scan = _escanear(tmp_path, dat, {"mal.nes": payload})
    (carpeta / "Juego (Europe).nes").write_bytes(b"NO ME PISES")

    planes = plan_renames(scan)

    assert not planes[0].can_apply
    assert "no se sobrescribe" in planes[0].skipped_reason
    apply_renames(planes)
    assert (carpeta / "Juego (Europe).nes").read_bytes() == b"NO ME PISES"
    assert (carpeta / "mal.nes").exists()


def test_dos_archivos_que_quieren_el_mismo_nombre_se_omiten_los_dos(tmp_path: Path) -> None:
    """Son copias del mismo contenido: elegir una por sorteo sería peor."""
    payload = b"ROM"
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": payload}})
    carpeta, scan = _escanear(tmp_path, dat, {"copia1.nes": payload, "copia2.nes": payload})

    planes = plan_renames(scan)

    assert len(planes) == 2
    assert all(not plan.can_apply for plan in planes)
    assert all("mismo nombre" in plan.skipped_reason for plan in planes)
    apply_renames(planes)
    assert sorted(item.name for item in carpeta.iterdir()) == ["copia1.nes", "copia2.nes"]


def test_se_conserva_la_extension_del_archivo(tmp_path: Path) -> None:
    """El DAT de Redump nombra pistas `.bin`, pero un CHD las trae todas dentro:
    renombrarlo a .bin rompería el romset."""
    from retroperfect.models import DatGame, DatRom, DetectedMetadata, RomHash, ScannedRom

    game = DatGame(name="Juego (Europe)", roms=[DatRom(name="Juego (Europe) (Track 1).bin", md5="0" * 32)])
    rom = ScannedRom(
        id="r",
        source_path="/roms/raro.chd",
        container_path="/roms/raro.chd",
        platform=Platform.PS1,
        hashes=RomHash(crc32="a", md5="0" * 32, sha1="b", size=10),
        dat_game=game,
        metadata=DetectedMetadata(title="Juego"),
    )

    assert expected_file_name(rom) == "Juego (Europe) (Track 1).chd"


def test_un_archivo_dentro_de_un_zip_se_omite_con_su_motivo(tmp_path: Path) -> None:
    """Renombrar una entrada comprimida obliga a reescribir el contenedor."""
    import zipfile

    payload = b"ROM"
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": payload}})
    carpeta = tmp_path / "roms"
    carpeta.mkdir()
    with zipfile.ZipFile(carpeta / "set.zip", "w") as zf:
        zf.writestr("mal.nes", payload)
    scan = scan_directory(carpeta, Platform.NES, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)

    planes = plan_renames(scan)

    assert len(planes) == 1
    assert not planes[0].can_apply
    assert "reempaquetar" in planes[0].skipped_reason


def test_un_cambio_de_solo_mayusculas_se_aplica(tmp_path: Path) -> None:
    """En macOS y Windows el sistema no distingue mayúsculas, así que el
    renombrado es sobre sí mismo y hay que pasar por un nombre intermedio."""
    payload = b"ROM"
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": payload}})
    carpeta, scan = _escanear(tmp_path, dat, {"juego (europe).nes": payload})

    planes = plan_renames(scan)
    assert planes[0].can_apply, planes[0].skipped_reason
    apply_renames(planes)

    assert [item.name for item in carpeta.iterdir()] == ["Juego (Europe).nes"]


def test_un_archivo_que_desaparecio_entre_el_escaneo_y_el_renombrado(tmp_path: Path) -> None:
    payload = b"ROM"
    dat = _dat(tmp_path / "nes.xml", {"Juego (Europe)": {"Juego (Europe).nes": payload}})
    carpeta, scan = _escanear(tmp_path, dat, {"mal.nes": payload})
    (carpeta / "mal.nes").unlink()

    log = apply_renames(plan_renames(scan))

    assert "ya no está" in log[0]
