"""Comparación de dos escaneos de la misma colección."""
from __future__ import annotations

from pathlib import Path

from retroperfect.models import Platform
from retroperfect.scan_diff import diff_scans
from retroperfect.scanner import scan_directory


def _escanear(carpeta: Path, archivos: dict[str, bytes]):
    carpeta.mkdir(parents=True, exist_ok=True)
    for item in carpeta.iterdir():
        item.unlink()
    for nombre, data in archivos.items():
        (carpeta / nombre).write_bytes(data)
    return scan_directory(carpeta, Platform.NES)


def test_dos_escaneos_iguales_no_tienen_diferencias(tmp_path: Path) -> None:
    carpeta = tmp_path / "roms"
    antes = _escanear(carpeta, {"a.nes": b"A", "b.nes": b"B"})
    despues = _escanear(carpeta, {"a.nes": b"A", "b.nes": b"B"})

    diff = diff_scans(antes, despues)

    assert diff.identical
    assert diff.unchanged == 2


def test_un_archivo_que_cambia_de_contenido_sin_cambiar_de_nombre(tmp_path: Path) -> None:
    """Es lo que no se nota mirando la carpeta: corrupción, una descarga que
    pisó otra, un parche aplicado por error."""
    carpeta = tmp_path / "roms"
    antes = _escanear(carpeta, {"a.nes": b"ORIGINAL"})
    despues = _escanear(carpeta, {"a.nes": b"CAMBIADO"})

    diff = diff_scans(antes, despues)

    assert len(diff.changed) == 1
    assert diff.changed[0].name == "a.nes"
    assert "MD5" in diff.changed[0].detail
    assert "mismo tamaño" in diff.changed[0].detail, "ocho bytes y ocho bytes: no es un truncamiento"
    assert not diff.added and not diff.removed


def test_un_cambio_de_tamano_se_distingue_de_uno_de_contenido(tmp_path: Path) -> None:
    carpeta = tmp_path / "roms"
    antes = _escanear(carpeta, {"a.nes": b"LARGO-LARGO"})
    despues = _escanear(carpeta, {"a.nes": b"CORTO"})

    diff = diff_scans(antes, despues)

    assert "11 → 5 bytes" in diff.changed[0].detail


def test_las_altas_y_las_bajas_se_reportan_aparte(tmp_path: Path) -> None:
    carpeta = tmp_path / "roms"
    antes = _escanear(carpeta, {"viejo.nes": b"VIEJO"})
    despues = _escanear(carpeta, {"nuevo.nes": b"NUEVO"})

    diff = diff_scans(antes, despues)

    assert [entry.name for entry in diff.added] == ["nuevo.nes"]
    assert [entry.name for entry in diff.removed] == ["viejo.nes"]
    assert not diff.changed and not diff.moved


def test_un_renombrado_no_se_cuenta_como_alta_mas_baja(tmp_path: Path) -> None:
    """El mismo contenido en otra ruta es un movimiento, no un archivo nuevo."""
    carpeta = tmp_path / "roms"
    antes = _escanear(carpeta, {"mal.nes": b"MISMO"})
    despues = _escanear(carpeta, {"Juego (Europe).nes": b"MISMO"})

    diff = diff_scans(antes, despues)

    assert [entry.name for entry in diff.moved] == ["Juego (Europe).nes"]
    assert "antes estaba en mal.nes" in diff.moved[0].detail
    assert not diff.added and not diff.removed


def test_lo_preocupante_sale_primero_en_la_lista(tmp_path: Path) -> None:
    carpeta = tmp_path / "roms"
    antes = _escanear(carpeta, {"a.nes": b"ORIGINAL", "se-va.nes": b"ADIOS"})
    despues = _escanear(carpeta, {"a.nes": b"CAMBIADO", "llega.nes": b"HOLA"})

    kinds = [entry.kind for entry in diff_scans(antes, despues).entries]

    assert kinds[0] == "cambiado"
    assert kinds.index("eliminado") < kinds.index("añadido")
