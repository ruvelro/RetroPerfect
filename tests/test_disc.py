from __future__ import annotations

import binascii
import hashlib
from pathlib import Path

from retroperfect.disc import DiscImage, disc_ra_md5, psp_ra_md5, psx_ra_md5, segacd_ra_md5

SECTOR = 2048


def _both_endian_32(value: int) -> bytes:
    return value.to_bytes(4, "little") + value.to_bytes(4, "big")


def _dir_record(name: bytes, sector: int, size: int, *, directory: bool = False) -> bytes:
    body = bytearray()
    body += b"\x00"  # ext attr
    body += _both_endian_32(sector)
    body += _both_endian_32(size)
    body += bytes(7)  # fecha
    body += bytes([0x02 if directory else 0x00])  # flags
    body += bytes(2)  # unit/gap
    body += (1).to_bytes(2, "little") + (1).to_bytes(2, "big")  # volumen
    body += bytes([len(name)]) + name
    if len(name) % 2 == 0:
        body += b"\x00"
    return bytes([len(body) + 1]) + bytes(body)


def _sector_pad(data: bytes) -> bytes:
    assert len(data) <= SECTOR
    return data + bytes(SECTOR - len(data))


def _build_iso(sectors: dict[int, bytes], total: int) -> bytes:
    image = bytearray(total * SECTOR)
    for index, data in sectors.items():
        image[index * SECTOR : index * SECTOR + len(data)] = data
    return bytes(image)


def _pvd(root_sector: int, root_size: int) -> bytes:
    pvd = bytearray(SECTOR)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[156 : 156 + 34] = _dir_record(b"\x00", root_sector, root_size, directory=True)[:34].ljust(34, b"\x00")
    return bytes(pvd)


def _psx_image() -> tuple[bytes, str]:
    cnf = b"BOOT = cdrom:\\SLUS_123.45;1\r\nTCB = 4\r\n"
    exe_payload = b"codigo-del-juego" * 10
    exe = b"PS-X EXE" + bytes(20) + len(exe_payload).to_bytes(4, "little") + bytes(2016 - 32) + exe_payload
    root = _sector_pad(_dir_record(b"SYSTEM.CNF;1", 21, len(cnf)) + _dir_record(b"SLUS_123.45;1", 22, len(exe)))
    sectors = {16: _pvd(20, SECTOR), 20: root, 21: _sector_pad(cnf)}
    image = bytearray(_build_iso(sectors, 26))
    image[22 * SECTOR : 22 * SECTOR + len(exe)] = exe
    clipped = exe[: len(exe_payload) + 2048]
    expected = hashlib.md5(b"SLUS_123.45;1" + clipped).hexdigest()
    return bytes(image), expected


def test_psx_ra_hash_from_iso(tmp_path: Path) -> None:
    image, expected = _psx_image()
    iso = tmp_path / "Juego (Europe).iso"
    iso.write_bytes(image)
    with DiscImage(iso) as disc:
        assert psx_ra_md5(disc) == expected
    assert disc_ra_md5(iso, "psx") == expected


def _raw_wrap(image: bytes) -> bytes:
    """Convierte una imagen 2048 en BIN crudo MODE1/2352 con sync+cabecera."""
    sync = b"\x00" + b"\xff" * 10 + b"\x00"
    out = bytearray()
    for index in range(0, len(image), SECTOR):
        header = bytes([0, 2, index // SECTOR % 75, 1])  # MSF ficticio + modo 1
        user = image[index : index + SECTOR]
        out += sync + header + user + bytes(2352 - 16 - SECTOR)
    return bytes(out)


def test_psx_ra_hash_from_bin_cue(tmp_path: Path) -> None:
    image, expected = _psx_image()
    bin_path = tmp_path / "Juego (Europe).bin"
    bin_path.write_bytes(_raw_wrap(image))
    cue_path = tmp_path / "Juego (Europe).cue"
    cue_path.write_text('FILE "Juego (Europe).bin" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\n', encoding="utf-8")
    assert disc_ra_md5(cue_path, "psx") == expected
    assert disc_ra_md5(bin_path, "psx") == expected


def test_segacd_ra_hash_is_first_512_bytes(tmp_path: Path) -> None:
    header = b"SEGADISCSYSTEM  " + b"X" * 496 + b"resto del sector"
    iso = tmp_path / "Juego (Europe).iso"
    iso.write_bytes(_sector_pad(header) + bytes(SECTOR))
    with DiscImage(iso) as disc:
        assert segacd_ra_md5(disc) == hashlib.md5(header[:512]).hexdigest()


def test_psp_ra_hash_uses_param_sfo_and_eboot(tmp_path: Path) -> None:
    param = b"\x00PSF-contenido-param-sfo"
    eboot = b"contenido-eboot" * 20
    sysdir = _sector_pad(_dir_record(b"EBOOT.BIN;1", 24, len(eboot)))
    psp_game = _sector_pad(_dir_record(b"PARAM.SFO;1", 23, len(param)) + _dir_record(b"SYSDIR", 22, SECTOR, directory=True))
    root = _sector_pad(_dir_record(b"PSP_GAME", 21, SECTOR, directory=True))
    sectors = {
        16: _pvd(20, SECTOR),
        20: root,
        21: psp_game,
        22: sysdir,
        23: _sector_pad(param),
    }
    image = bytearray(_build_iso(sectors, 26))
    image[24 * SECTOR : 24 * SECTOR + len(eboot)] = eboot
    iso = tmp_path / "Juego (Europe).iso"
    iso.write_bytes(bytes(image))
    with DiscImage(iso) as disc:
        assert psp_ra_md5(disc) == hashlib.md5(param + eboot).hexdigest()
    assert disc_ra_md5(iso, "psp") == hashlib.md5(param + eboot).hexdigest()


def test_disc_ra_md5_returns_none_for_broken_images(tmp_path: Path) -> None:
    broken = tmp_path / "roto.iso"
    broken.write_bytes(b"esto no es un iso")
    assert disc_ra_md5(broken, "psx") is None
    assert disc_ra_md5(broken, "direct") is None


def test_scanner_sets_disc_ra_hash(tmp_path: Path) -> None:
    from retroperfect.models import Platform
    from retroperfect.scanner import scan_directory

    image, expected = _psx_image()
    (tmp_path / "Juego (Europe).iso").write_bytes(image)
    cache = tmp_path / "cache.sqlite3"
    scan = scan_directory(tmp_path, Platform.PS1, hash_cache=cache)
    assert len(scan.roms) == 1
    assert scan.roms[0].hashes.ra_hash == expected
    # segunda pasada: el hash RA sobrevive al cache-hit
    again = scan_directory(tmp_path, Platform.PS1, hash_cache=cache)
    assert again.roms[0].hashes.ra_hash == expected
    # el crc del archivo completo sigue siendo el del contenido íntegro
    assert again.roms[0].hashes.crc32 == f"{binascii.crc32(image) & 0xFFFFFFFF:08x}"


def test_dreamcast_ra_hash_from_gdi(tmp_path: Path) -> None:
    from retroperfect.disc import GDI_HIGH_DENSITY_LBA, dreamcast_ra_md5

    base = GDI_HIGH_DENSITY_LBA
    boot = b"binario-de-arranque-dreamcast" * 30
    ip_bin = bytearray(SECTOR)
    ip_bin[0:16] = b"SEGA SEGAKATANA "
    ip_bin[16:32] = b"SEGA ENTERPRISES"
    ip_bin[0x60:0x70] = b"1ST_READ.BIN".ljust(16)
    root = _sector_pad(_dir_record(b"1ST_READ.BIN;1", base + 21, len(boot)))
    sectors = {
        0: bytes(ip_bin),
        16: _pvd(base + 20, SECTOR),
        20: root,
    }
    track = bytearray(_build_iso(sectors, 26))
    track[21 * SECTOR : 21 * SECTOR + len(boot)] = boot
    (tmp_path / "track03.bin").write_bytes(bytes(track))
    gdi = tmp_path / "Juego (Europe).gdi"
    gdi.write_text(
        f'3\n1 0 4 2352 "track01.bin" 0\n2 756 0 2352 "track02.raw" 0\n3 {base} 4 2048 "track03.bin" 0\n',
        encoding="utf-8",
    )
    expected = hashlib.md5(bytes(ip_bin[:256]) + boot).hexdigest()
    with DiscImage(gdi) as disc:
        assert disc.base_lba == base
        assert dreamcast_ra_md5(disc) == expected
    assert disc_ra_md5(gdi, "dreamcast") == expected


def test_dreamcast_gdi_rejects_non_katana_track(tmp_path: Path) -> None:
    (tmp_path / "track03.bin").write_bytes(bytes(SECTOR * 2))
    gdi = tmp_path / "otro.gdi"
    gdi.write_text('1\n3 45000 4 2048 "track03.bin" 0\n', encoding="utf-8")
    assert disc_ra_md5(gdi, "dreamcast") is None
