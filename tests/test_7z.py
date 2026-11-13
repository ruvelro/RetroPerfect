from __future__ import annotations

import io
from pathlib import Path

import py7zr

from retroperfect.models import Platform
from retroperfect.scanner import scan_directory


def _make_7z(path: Path, entries: dict[str, bytes]) -> None:
    with py7zr.SevenZipFile(path, "w") as archive:
        for name, data in entries.items():
            import io

            archive.writef(io.BytesIO(data), name)


def test_scan_reads_roms_inside_7z(tmp_path: Path) -> None:
    _make_7z(tmp_path / "Game (Europe).7z", {"Game (Europe).nes": b"EUR", "readme.txt": b"ignorar"})
    scan = scan_directory(tmp_path, Platform.NES)
    assert len(scan.roms) == 1
    rom = scan.roms[0]
    assert rom.inner_path == "Game (Europe).nes"
    assert rom.metadata.regions == ["Europe"]
    assert scan.unmatched_files == []


def test_scan_marks_7z_without_roms_as_unmatched(tmp_path: Path) -> None:
    _make_7z(tmp_path / "docs.7z", {"readme.txt": b"nada"})
    scan = scan_directory(tmp_path, Platform.NES)
    assert scan.roms == []
    assert len(scan.unmatched_files) == 1


def test_scan_marks_corrupt_7z_as_unmatched(tmp_path: Path) -> None:
    (tmp_path / "roto.7z").write_bytes(b"esto no es un 7z")
    scan = scan_directory(tmp_path, Platform.NES)
    assert scan.roms == []
    assert len(scan.unmatched_files) == 1


def test_scan_skips_oversized_7z_entries(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import scanner

    monkeypatch.setattr(scanner, "MAX_7Z_ENTRY_BYTES", 4)
    _make_7z(tmp_path / "Pack (USA).7z", {"Pequeno (USA).nes": b"OK", "Enorme (USA).nes": b"X" * 100})
    scan = scanner.scan_directory(tmp_path, Platform.NES)
    assert len(scan.roms) == 1
    assert scan.roms[0].inner_path == "Pequeno (USA).nes"
    assert len(scan.unmatched_files) == 1
    assert "límite de extracción" in scan.unmatched_files[0]


def test_un_7z_con_muchas_entradas_se_extrae_por_tandas(tmp_path, monkeypatch) -> None:
    """El límite por entrada no acotaba el total: un 7z con dos mil entradas
    pequeñas se traía todo a memoria de una vez."""
    from retroperfect import scanner as scanner_module

    archivo = tmp_path / "set.7z"
    contenidos = {f"Juego {i} (Europe).nes": f"ROM-{i}".encode() * 64 for i in range(12)}
    with py7zr.SevenZipFile(archivo, "w") as sevenzip:
        for nombre, data in contenidos.items():
            sevenzip.writef(io.BytesIO(data), nombre)

    tandas: list[int] = []
    original = scanner_module._read_7z_entries

    def contar(archive, targets, largest):
        tandas.append(len(targets))
        return original(archive, targets, largest)

    monkeypatch.setattr(scanner_module, "_read_7z_entries", contar)
    # Presupuesto minúsculo para forzar varias tandas con entradas de pocos bytes.
    monkeypatch.setattr(scanner_module, "MAX_7Z_BATCH_BYTES", 200)

    scan = scanner_module.scan_directory(tmp_path, Platform.NES)

    assert len(tandas) > 1, f"se extrajo todo de una vez: {tandas}"
    assert max(tandas) < len(contenidos)
    assert sum(tandas) == len(contenidos), "alguna entrada se quedó sin extraer"
    # El resultado es el mismo que sin trocear, y en el orden del archivo.
    assert [rom.inner_path for rom in scan.roms] == list(contenidos)
    assert {rom.hashes.size for rom in scan.roms} == {len(data) for data in contenidos.values()}


def test_las_tandas_del_7z_respetan_el_presupuesto() -> None:
    from retroperfect.scanner import _7z_batches

    class Entrada:
        def __init__(self, size: int) -> None:
            self.uncompressed = size
            self.filename = f"{size}.nes"

    tandas = list(_7z_batches([Entrada(300), Entrada(300), Entrada(300)], 700))
    assert [len(t) for t in tandas] == [2, 1]

    # Una entrada que por sí sola pasa del límite va sola, no se descarta.
    tandas = list(_7z_batches([Entrada(5000), Entrada(10)], 700))
    assert [len(t) for t in tandas] == [1, 1]
