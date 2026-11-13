from __future__ import annotations

import binascii
import hashlib
from pathlib import Path

from retroperfect.coverage import build_coverage
from retroperfect.dat import DatIndex, parse_logiqx_dat
from retroperfect.diagnostics import build_patch_queue, build_perfect_audit, detect_dat_warnings
from retroperfect.models import ActionMode, Manifest, ManifestEntry, OutputBucket, Platform
from retroperfect.profile import list_recommended_profiles
from retroperfect.scanner import scan_directory


def test_recommended_profiles_are_available() -> None:
    profiles = list_recommended_profiles()
    assert {"1G1R puro", "1G1R + RA", "España/Europa", "USA-first"} <= set(profiles)
    assert profiles["1G1R + RA"].auto_patch_ra is True
    assert profiles["USA-first"].outputs[0].region_priority[0] == "USA"


def test_nes_dat_warning_for_headered_dat_with_unheadered_romset(tmp_path: Path) -> None:
    payload = b"ROM"
    rom = tmp_path / "Game (Europe).unh"
    rom.write_bytes(payload)
    dat = tmp_path / "Nintendo - Nintendo Entertainment System (Headered).xml"
    full = b"NES\x1a" + bytes(12) + payload
    dat.write_text(
        f"""<datafile>
  <header><name>NES Headered</name></header>
  <game name="Game (Europe)"><description>Game (Europe)</description><rom name="Game (Europe).nes" size="{len(full)}" crc="{binascii.crc32(full) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(full).hexdigest()}" sha1="{hashlib.sha1(full).hexdigest()}"/></game>
</datafile>""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES)
    rows = detect_dat_warnings(Platform.NES, tmp_path, dat, scan)
    assert any("unheadered" in row.detail.lower() for row in rows)


def test_n64_dat_warning_for_endian_mismatch(tmp_path: Path) -> None:
    rom = tmp_path / "Game.v64"
    rom.write_bytes(b"\x37\x80\x40\x12DATA")
    dat = tmp_path / "Nintendo - Nintendo 64 (BigEndian).xml"
    dat.write_text("<datafile><header><name>Nintendo - Nintendo 64 BigEndian</name></header></datafile>", encoding="utf-8")
    scan = scan_directory(tmp_path, Platform.N64)
    rows = detect_dat_warnings(Platform.N64, tmp_path, dat, scan)
    assert any("endian" in row.item.lower() and "ByteSwapped" in row.detail for row in rows)


def test_perfect_audit_and_patch_queue(tmp_path: Path) -> None:
    payload = b"ROM"
    (tmp_path / "Game (Europe).nes").write_bytes(payload)
    dat = tmp_path / "nes.xml"
    dat.write_text(
        f"""<datafile>
  <game name="Game (Europe)"><description>Game (Europe)</description><release name="Game" region="Europe"/><rom name="Game (Europe).nes" size="{len(payload)}" crc="{binascii.crc32(payload) & 0xFFFFFFFF:08x}" md5="{hashlib.md5(payload).hexdigest()}" sha1="{hashlib.sha1(payload).hexdigest()}"/></game>
</datafile>""",
        encoding="utf-8",
    )
    scan = scan_directory(tmp_path, Platform.NES, DatIndex(parse_logiqx_dat(dat)), dat)
    manifest = Manifest(
        id="manifest",
        scan_id=scan.id,
        platform=Platform.NES,
        profile_snapshot={},
        entries=[
            ManifestEntry(
                bucket=OutputBucket.RA,
                action=ActionMode.COPY,
                source_path=scan.roms[0].container_path,
                destination_path=str(tmp_path / "out" / "Otros" / "RetroAchievements" / "Game RA.nes"),
                rom_id=scan.roms[0].id,
                patch_url="https://example.test/Game.ips",
                patch_expected_md5="abc",
            )
        ],
    )
    summary = build_coverage(scan, parse_logiqx_dat(dat), manifest)
    audit = build_perfect_audit(summary, scan, manifest)
    assert audit.patch_pending == 1
    assert build_patch_queue(manifest)[0].status == "Listo"


# --- preflight del origen ----------------------------------------------------


def test_el_preflight_avisa_si_el_origen_no_parece_de_la_plataforma(tmp_path: Path) -> None:
    """Apuntar el origen a la carpeta equivocada es el error más fácil de cometer."""
    from retroperfect.diagnostics import preflight_source_warnings

    origen = tmp_path / "roms"
    origen.mkdir()
    for nombre in ["a.iso", "b.iso", "c.cue"]:
        (origen / nombre).write_bytes(b"x")

    avisos = preflight_source_warnings(Platform.NES, origen)

    assert [aviso.item for aviso in avisos] == ["Origen"]
    assert "no parecen de" in avisos[0].detail
    assert ".iso: 2" in avisos[0].detail


def test_el_preflight_calla_si_el_origen_cuadra(tmp_path: Path) -> None:
    from retroperfect.diagnostics import preflight_source_warnings

    origen = tmp_path / "roms"
    origen.mkdir()
    (origen / "Juego (Europe).nes").write_bytes(b"x")

    assert preflight_source_warnings(Platform.NES, origen) == []
    assert preflight_source_warnings(Platform.NES, None) == []
    assert preflight_source_warnings(Platform.NES, tmp_path / "no-existe") == []


def test_el_preflight_avisa_del_desajuste_de_endianness_de_n64(tmp_path: Path) -> None:
    from retroperfect.diagnostics import preflight_source_warnings

    origen = tmp_path / "roms"
    origen.mkdir()
    (origen / "Juego (Europe).v64").write_bytes(b"x")

    avisos = preflight_source_warnings(Platform.N64, origen, tmp_path / "Nintendo 64 (BigEndian).dat")

    assert any(aviso.item == "Preflight N64" for aviso in avisos)


def test_el_preflight_avisa_de_bin_contra_un_dat_a78(tmp_path: Path) -> None:
    from retroperfect.diagnostics import preflight_source_warnings

    origen = tmp_path / "roms"
    origen.mkdir()
    (origen / "Juego (Europe).bin").write_bytes(b"x")

    avisos = preflight_source_warnings(Platform.A7800, origen, tmp_path / "Atari 7800 (a78).dat")

    assert any(aviso.item == "Preflight A7800" for aviso in avisos)


def test_el_preflight_arcade_avisa_de_chd_sin_sus_sets(tmp_path: Path) -> None:
    from retroperfect.diagnostics import preflight_source_warnings

    origen = tmp_path / "roms"
    origen.mkdir()
    (origen / "juego.chd").write_bytes(b"x")

    avisos = preflight_source_warnings(Platform.MAME, origen)

    assert any("CHDs pero no se ven ZIP" in aviso.detail for aviso in avisos)


def test_el_preflight_arcade_explica_como_trata_los_zip(tmp_path: Path) -> None:
    import zipfile

    from retroperfect.diagnostics import preflight_source_warnings

    origen = tmp_path / "roms"
    origen.mkdir()
    with zipfile.ZipFile(origen / "set.zip", "w") as zf:
        for indice in range(5):
            zf.writestr(f"rom{indice}.bin", b"x")

    avisos = preflight_source_warnings(Platform.MAME, origen)

    assert any("sets completos por nombre" in aviso.detail for aviso in avisos)


# --- avisos de arcade --------------------------------------------------------


def test_un_dat_de_consola_en_una_plataforma_arcade_se_avisa(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import dat_sources
    from retroperfect.dat_manager import import_dat_file
    from retroperfect.diagnostics import detect_dat_warnings

    # Sin esto, importar escribe en la biblioteca DAT real del usuario: el test
    # le dejaba un DAT de un juego metido entre los suyos en cada ejecución.
    monkeypatch.setattr(dat_sources, "data_dir", lambda: tmp_path / "datos")

    dat = tmp_path / "Nintendo - NES.dat"
    dat.write_text(
        '<?xml version="1.0"?><datafile><header><name>Nintendo - NES</name></header>'
        '<game name="Juego"><description>Juego</description><rom name="Juego.nes" size="3" crc="aabbccdd"/></game></datafile>',
        encoding="utf-8",
    )
    import_dat_file(dat)

    avisos = detect_dat_warnings(Platform.MAME, None, dat)

    assert any(aviso.item == "Arcade DAT" for aviso in avisos)
    assert any(aviso.item == "Arcade" for aviso in avisos), "siempre se explica cómo funciona arcade"


# --- filas de "lo que necesitas" ---------------------------------------------


def test_las_filas_de_lo_necesario_dicen_que_falta(tmp_path: Path) -> None:
    from retroperfect.diagnostics import build_needed_rows

    filas = {fila.item: fila for fila in build_needed_rows(Platform.SNES, None, None)}

    assert filas["Romset/origen"].status == "MISS"
    assert filas["DAT recomendado"].detail
    assert filas["Romset recomendado"].recommendation


# --- helpers de cabecera y endianness ---------------------------------------


def test_el_modo_del_dat_de_n64_se_deduce_del_nombre() -> None:
    from retroperfect.diagnostics import _n64_dat_mode

    assert _n64_dat_mode("nintendo 64 (bigendian)") == "BigEndian"
    assert _n64_dat_mode("nintendo 64 (byte swapped)") == "ByteSwapped"
    assert _n64_dat_mode("nintendo 64 (littleendian)") == "LittleEndian"
    assert _n64_dat_mode("nintendo 64") is None


def test_el_modo_del_romset_de_n64_sale_de_las_extensiones(tmp_path: Path) -> None:
    from retroperfect.diagnostics import _n64_rom_mode
    from retroperfect.scanner import scan_directory

    for nombre in ["a.z64", "b.z64", "c.v64"]:
        (tmp_path / nombre).write_bytes(b"\x80\x37\x12\x40DATOS")

    assert _n64_rom_mode(scan_directory(tmp_path, Platform.N64)) == "BigEndian"
    assert _n64_rom_mode(None) is None


def test_un_zip_ilegible_no_rompe_el_preflight(tmp_path: Path) -> None:
    from retroperfect.diagnostics import _zip_has_many_inner_roms

    roto = tmp_path / "roto.zip"
    roto.write_bytes(b"esto no es un zip")

    assert _zip_has_many_inner_roms(roto) is False
