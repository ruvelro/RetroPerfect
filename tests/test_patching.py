from __future__ import annotations

import binascii
import hashlib
import struct
from pathlib import Path

import pytest

from retroperfect.manifest_io import apply_manifest
from retroperfect.models import ActionMode, Manifest, ManifestEntry, OutputBucket, Platform
from retroperfect.patching import PatchPayload, apply_bps, apply_ips


def test_apply_ips_patch() -> None:
    patch = b"PATCH" + (1).to_bytes(3, "big") + (1).to_bytes(2, "big") + b"A" + b"EOF"
    assert apply_ips(b"abc", patch) == b"aAc"


def test_apply_manifest_patch_entry_verifies_expected_md5(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "Game.nes"
    source.write_bytes(b"abc")
    patched = b"aAc"

    def fake_download_and_apply_patch(data: bytes, patch_url: str):
        assert data == b"abc"
        assert patch_url == "https://example.test/patch.zip"
        return patched, PatchPayload("patch.ips", ".ips", b"")

    monkeypatch.setattr("retroperfect.manifest_io.download_and_apply_patch", fake_download_and_apply_patch)
    manifest = Manifest(
        id="manifest",
        scan_id="scan",
        platform=Platform.NES,
        profile_snapshot={},
        entries=[
            ManifestEntry(
                bucket=OutputBucket.RA,
                action=ActionMode.COPY,
                source_path=str(source),
                destination_path=str(tmp_path / "out" / "Otros" / "RetroAchievements" / "Game RA.nes"),
                rom_id="rom",
                patch_url="https://example.test/patch.zip",
                patch_expected_md5=hashlib.md5(patched).hexdigest(),
            )
        ],
    )
    completed = apply_manifest(manifest, ActionMode.COPY, confirm=True)
    assert "parcheado" in completed[0]
    assert (tmp_path / "out" / "Otros" / "RetroAchievements" / "Game RA.nes").read_bytes() == patched


def test_download_patch_caches_per_url_not_per_filename(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import patching

    monkeypatch.setattr(patching, "data_dir", lambda: tmp_path)
    payloads = {
        "https://example.test/game-a/patch.ips": b"A",
        "https://example.test/game-b/patch.ips": b"B",
    }

    class Response:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(patching, "http_get", lambda url, **kwargs: Response(payloads[url]))
    path_a = patching.download_patch("https://example.test/game-a/patch.ips")
    path_b = patching.download_patch("https://example.test/game-b/patch.ips")
    assert path_a != path_b
    assert path_a.read_bytes() == b"A"
    assert path_b.read_bytes() == b"B"
    assert path_a.name == "patch.ips"
    monkeypatch.setattr(patching, "http_get", lambda url, **kwargs: (_ for _ in ()).throw(AssertionError("no debe descargar de nuevo")))
    assert patching.download_patch("https://example.test/game-a/patch.ips") == path_a


def _ups_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value == 0:
            out.append(chunk | 0x80)
            return bytes(out)
        out.append(chunk)
        value -= 1


def test_apply_ups_patch() -> None:
    import binascii
    import struct

    from retroperfect.patching import apply_ups

    source = b"abcdef"
    target = b"aXcdeF"
    body = b"UPS1" + _ups_varint(len(source)) + _ups_varint(len(target))
    # bloque 1: saltar 1, XOR en offset 1
    body += _ups_varint(1) + bytes([ord("b") ^ ord("X")]) + b"\x00"
    # bloque 2: el terminador anterior dejó el puntero en 3; saltar 2 hasta offset 5
    body += _ups_varint(2) + bytes([ord("f") ^ ord("F")]) + b"\x00"
    body += struct.pack("<II", binascii.crc32(source) & 0xFFFFFFFF, binascii.crc32(target) & 0xFFFFFFFF)
    patch = body + struct.pack("<I", binascii.crc32(body) & 0xFFFFFFFF)
    assert apply_ups(source, patch) == target


def test_apply_ups_rejects_wrong_source() -> None:
    import binascii
    import struct

    import pytest

    from retroperfect.patching import apply_ups

    source = b"abcdef"
    body = b"UPS1" + _ups_varint(6) + _ups_varint(6) + struct.pack("<II", binascii.crc32(source) & 0xFFFFFFFF, binascii.crc32(source) & 0xFFFFFFFF)
    patch = body + struct.pack("<I", binascii.crc32(body) & 0xFFFFFFFF)
    with pytest.raises(ValueError, match="CRC de ROM origen"):
        apply_ups(b"otra-rom", patch)


def test_apply_xdelta_roundtrip(tmp_path: Path) -> None:
    import pyxdelta

    from retroperfect.patching import apply_xdelta

    source = b"hola mundo " * 200
    target = b"hola MUNDO " * 200 + b"cola nueva"
    src = tmp_path / "src.bin"
    dst = tmp_path / "dst.bin"
    patch = tmp_path / "p.xdelta"
    src.write_bytes(source)
    dst.write_bytes(target)
    assert pyxdelta.run(str(src), str(dst), str(patch))
    assert apply_xdelta(source, patch.read_bytes()) == target


def test_apply_ppf3_patch() -> None:
    from retroperfect.patching import apply_ppf

    source = bytes(64)
    header = b"PPF30" + bytes([2]) + b"desc".ljust(50, b"\x00") + bytes([0]) + bytes([0]) + bytes([0]) + bytes([0])
    record = (10).to_bytes(8, "little") + bytes([3]) + b"ABC"
    patched = apply_ppf(source, header + record)
    assert patched[10:13] == b"ABC"
    assert len(patched) == 64


def test_apply_ppf3_with_undo_and_file_id() -> None:
    from retroperfect.patching import apply_ppf

    source = bytes(32)
    header = b"PPF30" + bytes([2]) + bytes(50) + bytes([0]) + bytes([0]) + bytes([1]) + bytes([0])  # con undo
    record = (4).to_bytes(8, "little") + bytes([2]) + b"XY" + b"\x00\x00"  # datos + undo
    trailer = b"@BEGIN_FILE_ID.DIZ" + b"comentario" + b"@END_FILE_ID.DIZ"
    patched = apply_ppf(source, header + record + trailer)
    assert patched[4:6] == b"XY"


def test_apply_ppf2_checks_size_and_blockcheck() -> None:
    import pytest

    from retroperfect.patching import PPF_BLOCKCHECK_OFFSET, apply_ppf

    source = bytearray(PPF_BLOCKCHECK_OFFSET + 2048)
    source[PPF_BLOCKCHECK_OFFSET : PPF_BLOCKCHECK_OFFSET + 4] = b"SYNC"
    source = bytes(source)
    blockcheck = source[PPF_BLOCKCHECK_OFFSET : PPF_BLOCKCHECK_OFFSET + 1024]
    header = b"PPF20" + bytes([1]) + bytes(50) + len(source).to_bytes(4, "little") + blockcheck
    record = (8).to_bytes(4, "little") + bytes([2]) + b"OK"
    patched = apply_ppf(source, header + record)
    assert patched[8:10] == b"OK"

    wrong_size = header.replace(len(source).to_bytes(4, "little"), (123).to_bytes(4, "little"))
    with pytest.raises(ValueError, match="tamaño"):
        apply_ppf(source, wrong_size + record)


def _aps_header(patch_type: int, crc: bytes = b"\x00" * 8) -> bytes:
    header = b"APS10" + bytes([patch_type]) + bytes([0]) + b"desc".ljust(50, b"\x00")
    if patch_type == 1:
        header += bytes([1]) + b"NSM" + crc + bytes(5)
    return header


def test_apply_aps_simple_with_rle() -> None:
    from retroperfect.patching import apply_aps

    source = bytes(32)
    records = (4).to_bytes(4, "little") + bytes([2]) + b"AB"
    records += (10).to_bytes(4, "little") + bytes([0]) + bytes([0xFF]) + bytes([3])  # RLE: 3x 0xFF
    patch = _aps_header(0) + (32).to_bytes(4, "little") + records
    patched = apply_aps(source, patch)
    assert patched[4:6] == b"AB"
    assert patched[10:13] == b"\xff\xff\xff"
    assert len(patched) == 32


def test_apply_aps_n64_validates_header_crc() -> None:
    import pytest

    from retroperfect.patching import apply_aps

    crc = bytes(range(8))
    source = bytearray(64)
    source[0x10:0x18] = crc
    source = bytes(source)
    records = (0x20).to_bytes(4, "little") + bytes([1]) + b"Z"
    patch = _aps_header(1, crc) + (64).to_bytes(4, "little") + records
    patched = apply_aps(source, patch)
    assert patched[0x20] == ord("Z")

    wrong = _aps_header(1, b"\xaa" * 8) + (64).to_bytes(4, "little") + records
    with pytest.raises(ValueError, match="CRC de cabecera"):
        apply_aps(source, wrong)


# --- BPS ---------------------------------------------------------------------


def _bps_number(value: int) -> bytes:
    """Varint de BPS: siete bits por byte, el último con el bit alto puesto."""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value == 0:
            out.append(0x80 | byte)
            break
        value -= 1
        out.append(byte)
    return bytes(out)


def _bps_patch(source: bytes, acciones: bytes, target: bytes, *, metadata: bytes = b"") -> bytes:
    cuerpo = (
        _bps_number(len(source))
        + _bps_number(len(target))
        + _bps_number(len(metadata))
        + metadata
        + acciones
    )
    cuerpo = b"BPS1" + cuerpo
    pies = struct.pack("<II", binascii.crc32(source) & 0xFFFFFFFF, binascii.crc32(target) & 0xFFFFFFFF)
    sin_crc = cuerpo + pies
    return sin_crc + struct.pack("<I", binascii.crc32(sin_crc) & 0xFFFFFFFF)


def _bps_source_read(length: int) -> bytes:
    return _bps_number(((length - 1) << 2) | 0)


def _bps_target_read(data: bytes) -> bytes:
    return _bps_number(((len(data) - 1) << 2) | 1) + data


def test_apply_bps_copia_del_origen_y_escribe_literales() -> None:
    """BPS lo anuncia el README y no tenía ni un test."""
    source = b"0123456789"
    target = b"012XY56789"
    acciones = _bps_source_read(3) + _bps_target_read(b"XY") + _bps_source_read(5)

    assert apply_bps(source, _bps_patch(source, acciones, target)) == target


def test_apply_bps_admite_metadatos_y_un_target_mas_largo() -> None:
    source = b"ABCD"
    target = b"ABCD-EXTRA"
    acciones = _bps_source_read(4) + _bps_target_read(b"-EXTRA")

    assert apply_bps(source, _bps_patch(source, acciones, target, metadata=b"<xml/>")) == target


def test_apply_bps_rechaza_una_cabecera_que_no_es_bps() -> None:
    with pytest.raises(ValueError, match="cabecera BPS1"):
        apply_bps(b"ABCD", b"NOPE" + b"\x80" * 20)


def test_apply_bps_rechaza_un_parche_truncado() -> None:
    with pytest.raises(ValueError, match="demasiado pequeño"):
        apply_bps(b"ABCD", b"BPS1" + b"\x80")


def test_apply_bps_detecta_un_parche_corrupto() -> None:
    source = b"0123456789"
    target = b"012XY56789"
    patch = bytearray(_bps_patch(source, _bps_source_read(3) + _bps_target_read(b"XY") + _bps_source_read(5), target))
    patch[10] ^= 0xFF  # altera el cuerpo sin recalcular su CRC

    with pytest.raises(ValueError, match="CRC del parche"):
        apply_bps(source, bytes(patch))


def test_apply_bps_rechaza_la_rom_equivocada() -> None:
    source = b"0123456789"
    target = b"012XY56789"
    patch = _bps_patch(source, _bps_source_read(3) + _bps_target_read(b"XY") + _bps_source_read(5), target)

    with pytest.raises(ValueError, match="CRC de ROM origen"):
        apply_bps(b"otra rom distinta", patch)


def test_apply_bps_rechaza_un_tamano_de_origen_distinto() -> None:
    """El CRC puede cuadrar y el tamaño declarado no: se comprueban los dos."""
    source = b"0123456789"
    target = b"0123456789"
    cuerpo = b"BPS1" + _bps_number(99) + _bps_number(len(target)) + _bps_number(0) + _bps_source_read(10)
    pies = struct.pack("<II", binascii.crc32(source) & 0xFFFFFFFF, binascii.crc32(target) & 0xFFFFFFFF)
    patch = cuerpo + pies
    patch += struct.pack("<I", binascii.crc32(patch) & 0xFFFFFFFF)

    with pytest.raises(ValueError, match="tamaño de ROM origen"):
        apply_bps(source, patch)


def test_apply_bps_avisa_si_el_resultado_no_cuadra() -> None:
    """Un parche cuyo pie declara otro target: el resultado no se da por bueno."""
    source = b"0123456789"
    acciones = _bps_source_read(10)
    cuerpo = b"BPS1" + _bps_number(len(source)) + _bps_number(len(source)) + _bps_number(0) + acciones
    pies = struct.pack("<II", binascii.crc32(source) & 0xFFFFFFFF, 0xDEADBEEF)
    patch = cuerpo + pies
    patch += struct.pack("<I", binascii.crc32(patch) & 0xFFFFFFFF)

    with pytest.raises(ValueError, match="CRC final"):
        apply_bps(source, patch)


# --- IPS: casos que no eran el feliz ----------------------------------------


def test_apply_ips_expande_un_registro_rle() -> None:
    """Un registro de tamaño 0 significa "repite este byte N veces"."""
    patch = b"PATCH" + (2).to_bytes(3, "big") + (0).to_bytes(2, "big") + (4).to_bytes(2, "big") + b"Z" + b"EOF"

    assert apply_ips(b"abcdef", patch) == b"abZZZZ"


def test_apply_ips_trunca_cuando_el_parche_lo_pide() -> None:
    patch = b"PATCH" + (0).to_bytes(3, "big") + (1).to_bytes(2, "big") + b"X" + b"EOF" + (3).to_bytes(3, "big")

    assert apply_ips(b"abcdef", patch) == b"Xbc"


def test_apply_ips_alarga_la_rom_si_el_registro_cae_mas_alla_del_final() -> None:
    patch = b"PATCH" + (4).to_bytes(3, "big") + (2).to_bytes(2, "big") + b"YZ" + b"EOF"

    assert apply_ips(b"abc", patch) == b"abc\x00YZ"


def test_apply_ips_rechaza_lo_que_no_es_un_ips() -> None:
    with pytest.raises(ValueError, match="cabecera PATCH"):
        apply_ips(b"abc", b"NOPE")


def test_apply_ips_avisa_de_un_parche_cortado() -> None:
    for truncado, motivo in [
        (b"PATCH" + (0).to_bytes(3, "big"), "registro incompleto"),
        (b"PATCH" + (0).to_bytes(3, "big") + (0).to_bytes(2, "big") + b"\x00", "RLE incompleto"),
        (b"PATCH" + (0).to_bytes(3, "big") + (9).to_bytes(2, "big") + b"ab", "datos incompletos"),
    ]:
        with pytest.raises(ValueError, match=motivo):
            apply_ips(b"abc", truncado)


# --- selección del parche dentro de un contenedor ----------------------------


def test_un_zip_con_varios_parches_elige_de_forma_estable(tmp_path: Path) -> None:
    import zipfile

    from retroperfect.patching import load_patch_payload

    archivo = tmp_path / "parches.zip"
    with zipfile.ZipFile(archivo, "w") as zf:
        zf.writestr("z-ultimo.ips", b"PATCH" + b"EOF")
        zf.writestr("a-primero.bps", b"BPS1" + b"\x00" * 16)
        zf.writestr("leeme.txt", b"no soy un parche")

    payload = load_patch_payload(archivo)

    assert payload.name == "a-primero.bps", "con varios candidatos se elige por orden alfabético, no al azar"
    assert payload.suffix == ".bps"


def test_un_zip_con_solo_un_formato_no_soportado_lo_dice(tmp_path: Path) -> None:
    import zipfile

    from retroperfect.patching import load_patch_payload

    archivo = tmp_path / "rup.zip"
    with zipfile.ZipFile(archivo, "w") as zf:
        zf.writestr("parche.rup", b"RUP")

    with pytest.raises(ValueError, match="no está soportado"):
        load_patch_payload(archivo)


def test_un_zip_sin_parches_lo_dice(tmp_path: Path) -> None:
    import zipfile

    from retroperfect.patching import load_patch_payload

    archivo = tmp_path / "vacio.zip"
    with zipfile.ZipFile(archivo, "w") as zf:
        zf.writestr("leeme.txt", b"nada")

    with pytest.raises(ValueError, match="no contiene parches"):
        load_patch_payload(archivo)


def test_un_rup_suelto_se_rechaza_con_su_nombre(tmp_path: Path) -> None:
    from retroperfect.patching import load_patch_payload

    archivo = tmp_path / "parche.rup"
    archivo.write_bytes(b"RUP")

    with pytest.raises(ValueError, match="no soportado todavía"):
        load_patch_payload(archivo)


def test_una_extension_desconocida_se_rechaza(tmp_path: Path) -> None:
    from retroperfect.patching import load_patch_payload

    archivo = tmp_path / "parche.quesea"
    archivo.write_bytes(b"??")

    with pytest.raises(ValueError, match="No se encontró un parche soportado"):
        load_patch_payload(archivo)


def test_aplicar_un_formato_que_no_se_sabe_aplicar_se_rechaza() -> None:
    from retroperfect.patching import apply_patch_bytes

    with pytest.raises(ValueError, match="no soportado"):
        apply_patch_bytes(b"rom", PatchPayload(name="x.rup", suffix=".rup", data=b"RUP"))
