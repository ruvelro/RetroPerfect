"""Llenar un dispositivo con lo que quepa, sin pasarse del tamaño.

No es un camino nuevo que toque archivos: es un plan recortado, así que hereda
la verificación, la idempotencia y el deshacer de `apply`. Lo que se prueba aquí
es la decisión de qué entra.
"""
from __future__ import annotations

import binascii
import hashlib
from pathlib import Path

import pytest

from retroperfect.dat import DatIndex, parse_dat
from retroperfect.device_sync import parse_budget, plan_device_sync
from retroperfect.manifest_io import apply_manifest
from retroperfect.models import ActionMode, OutputBucket, Platform, ProfileOutput, SelectionProfile
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


def _coleccion(tmp_path: Path, juegos: dict[str, dict[str, bytes]], platform: Platform = Platform.NES):
    dat = _dat(tmp_path / "dat.xml", juegos)
    carpeta = tmp_path / "roms"
    carpeta.mkdir(exist_ok=True)
    for roms in juegos.values():
        for nombre, data in roms.items():
            (carpeta / nombre).write_bytes(data)
    scan = scan_directory(carpeta, platform, dat_index=DatIndex(parse_dat(dat)), dat_path=dat)
    manifest = build_manifest(scan, PERFIL, [OutputBucket.MAIN], output_dir=tmp_path / "sd", action=ActionMode.COPY)
    return scan, manifest


def test_entran_los_que_caben_y_se_dice_quien_se_queda_fuera(tmp_path: Path) -> None:
    juegos = {
        "Pequeño (Europe)": {"Pequeño (Europe).nes": b"A" * 10},
        "Mediano (Europe)": {"Mediano (Europe).nes": b"B" * 30},
        "Grande (Europe)": {"Grande (Europe).nes": b"C" * 100},
    }
    scan, manifest = _coleccion(tmp_path, juegos)

    plan, report = plan_device_sync(manifest, scan, tmp_path / "sd", budget=45, order="size")

    assert [juego.title for juego in report.included] == ["Pequeño", "Mediano"]
    assert [juego.title for juego in report.excluded] == ["Grande"]
    assert report.bytes_planned == 40
    assert report.bytes_left == 5
    assert len(plan.entries) == 2


def test_un_juego_grande_no_corta_la_lista(tmp_path: Path) -> None:
    """Si uno grande cortara, un solo juego de 8 GB dejaría la tarjeta vacía."""
    juegos = {
        "Grande (Europe)": {"Grande (Europe).nes": b"C" * 100},
        "Cabe (Europe)": {"Cabe (Europe).nes": b"A" * 10},
    }
    scan, manifest = _coleccion(tmp_path, juegos)

    _plan, report = plan_device_sync(manifest, scan, tmp_path / "sd", budget=50, order="name")

    assert [juego.title for juego in report.included] == ["Cabe"]
    assert [juego.title for juego in report.excluded] == ["Grande"]


def test_un_juego_de_varios_discos_entra_entero_o_no_entra(tmp_path: Path) -> None:
    """Medio juego ocupa sitio y no se puede terminar: el mismo razonamiento por
    el que los discos no compiten entre sí en el 1G1R."""
    juegos = {
        "Saga (Europe) (Disc 1)": {"Saga (Europe) (Disc 1).iso": b"1" * 40},
        "Saga (Europe) (Disc 2)": {"Saga (Europe) (Disc 2).iso": b"2" * 40},
        "Suelto (Europe)": {"Suelto (Europe).iso": b"S" * 10},
    }
    scan, manifest = _coleccion(tmp_path, juegos, platform=Platform.PS1)

    # Con 90 caben el suelto (10) y la saga entera (40 + 40).
    _plan, report = plan_device_sync(manifest, scan, tmp_path / "sd", budget=90, order="size")

    assert [juego.title for juego in report.included] == ["Suelto", "Saga"]
    saga = next(juego for juego in report.included if juego.title == "Saga")
    assert saga.files == 2 and saga.size == 80, "el juego se mide con todos sus discos"

    # Con presupuesto para uno solo, la saga no entra a medias.
    _plan, estrecho = plan_device_sync(manifest, scan, tmp_path / "sd", budget=50, order="size")
    assert [juego.title for juego in estrecho.included] == ["Suelto"]
    assert [juego.title for juego in estrecho.excluded] == ["Saga"]


def test_el_orden_por_nombre_es_alfabetico(tmp_path: Path) -> None:
    juegos = {
        "Zelda (Europe)": {"Zelda (Europe).nes": b"Z" * 10},
        "Contra (Europe)": {"Contra (Europe).nes": b"C" * 10},
        "Metroid (Europe)": {"Metroid (Europe).nes": b"M" * 10},
    }
    scan, manifest = _coleccion(tmp_path, juegos)

    _plan, report = plan_device_sync(manifest, scan, tmp_path / "sd", budget=25, order="name")

    assert [juego.title for juego in report.included] == ["Contra", "Metroid"]


def test_el_orden_ra_mete_primero_los_que_tienen_logros(tmp_path: Path) -> None:
    juegos = {
        "ConLogros (Europe)": {"ConLogros (Europe).nes": b"L" * 50},
        "SinLogros (Europe)": {"SinLogros (Europe).nes": b"S" * 10},
    }
    scan, manifest = _coleccion(tmp_path, juegos)
    for entry in manifest.entries:
        if "ConLogros" in entry.source_path:
            entry.ra_game_id = 7

    _plan, report = plan_device_sync(manifest, scan, tmp_path / "sd", budget=55, order="ra")

    assert [juego.title for juego in report.included] == ["ConLogros"]
    assert report.ra_included == 1


def test_un_orden_desconocido_se_rechaza(tmp_path: Path) -> None:
    scan, manifest = _coleccion(tmp_path, {"Juego (Europe)": {"Juego (Europe).nes": b"A"}})

    with pytest.raises(ValueError, match="Orden desconocido"):
        plan_device_sync(manifest, scan, tmp_path / "sd", budget=100, order="por-color")


def test_las_playlists_de_un_juego_que_no_entra_se_quitan(tmp_path: Path) -> None:
    """Un .m3u que liste discos que no están es peor que no tenerlo."""
    juegos = {
        "Saga (Europe) (Disc 1)": {"Saga (Europe) (Disc 1).iso": b"1" * 40},
        "Saga (Europe) (Disc 2)": {"Saga (Europe) (Disc 2).iso": b"2" * 40},
    }
    scan, manifest = _coleccion(tmp_path, juegos, platform=Platform.PS1)
    assert manifest.playlists, "el escenario tiene que traer playlist"

    plan, _report = plan_device_sync(manifest, scan, tmp_path / "sd", budget=10, order="size")

    assert plan.entries == []
    assert plan.playlists == []


def test_el_plan_del_dispositivo_se_aplica_como_cualquier_otro(tmp_path: Path) -> None:
    """Hereda verificación por MD5 e idempotencia: no hay un camino nuevo."""
    juegos = {
        "Cabe (Europe)": {"Cabe (Europe).nes": b"A" * 10},
        "No cabe (Europe)": {"No cabe (Europe).nes": b"B" * 100},
    }
    scan, manifest = _coleccion(tmp_path, juegos)
    plan, _report = plan_device_sync(manifest, scan, tmp_path / "sd", budget=50, order="size")

    completed = apply_manifest(plan, confirm=True)
    segunda = apply_manifest(plan, confirm=True)

    destino = tmp_path / "sd" / "main"
    assert sorted(item.name for item in destino.iterdir()) == ["Cabe (Europe).nes"]
    assert "md5 verificado" in completed[0]
    assert "ya estaba aplicado" in segunda[0]


def test_el_presupuesto_admite_las_dos_convenciones_de_tamano() -> None:
    """Las tarjetas se venden en GB decimales y el sistema las mide en GiB: dar
    por supuesta una de las dos es prometer un hueco que no existe."""
    assert parse_budget("32GB") == 32_000_000_000
    assert parse_budget("32GiB") == 34_359_738_368
    assert parse_budget("512MiB") == 536_870_912
    assert parse_budget("1.5GB") == 1_500_000_000
    assert parse_budget("  8 gb  ") == 8_000_000_000
    assert parse_budget("2048") == 2048

    for malo in ["", "abc", "-5GB", "0", "GB"]:
        with pytest.raises(ValueError):
            parse_budget(malo)
