from __future__ import annotations

import binascii
import hashlib

from .models import Platform, RomHash
from .platforms import platform_spec

INES_HEADER_SIZE = 16
SNES_COPIER_HEADER_SIZE = 512
FDS_HEADER_SIZE = 16
LYNX_HEADER_SIZE = 64
A78_HEADER_SIZE = 128
PCE_HEADER_SIZE = 512
HASH_CHUNK_SIZE = 1024 * 1024

# Modos que necesitan el archivo completo en memoria para derivar el payload/hash RA.
# El resto (incluidos los modos de disco psx/segacd/psp) hashea en streaming: su hash
# RA se calcula aparte leyendo solo los sectores necesarios.
HEADER_HASH_MODES = {"nes", "snes", "n64", "fds", "lynx", "a78", "pce", "nds"}


def hash_stream(fh) -> RomHash:
    """Hash a binary stream in chunks; only valid when payload == data (hash_mode 'direct')."""
    crc = 0
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    size = 0
    while chunk := fh.read(HASH_CHUNK_SIZE):
        crc = binascii.crc32(chunk, crc)
        md5.update(chunk)
        sha1.update(chunk)
        size += len(chunk)
    crc_hex = f"{crc & 0xFFFFFFFF:08x}"
    md5_hex = md5.hexdigest()
    sha1_hex = sha1.hexdigest()
    return RomHash(
        crc32=crc_hex,
        md5=md5_hex,
        sha1=sha1_hex,
        size=size,
        payload_crc32=crc_hex,
        payload_md5=md5_hex,
        payload_sha1=sha1_hex,
        payload_size=size,
    )


def hash_bytes(data: bytes, platform: Platform = Platform.NES) -> RomHash:
    payload = payload_for_platform(data, platform)
    crc32 = f"{binascii.crc32(data) & 0xFFFFFFFF:08x}"
    md5 = hashlib.md5(data).hexdigest()
    sha1 = hashlib.sha1(data).hexdigest()
    if payload is data:
        payload_crc32, payload_md5, payload_sha1 = crc32, md5, sha1
    else:
        payload_crc32 = f"{binascii.crc32(payload) & 0xFFFFFFFF:08x}"
        payload_md5 = hashlib.md5(payload).hexdigest()
        payload_sha1 = hashlib.sha1(payload).hexdigest()
    return RomHash(
        crc32=crc32,
        md5=md5,
        sha1=sha1,
        size=len(data),
        payload_crc32=payload_crc32,
        payload_md5=payload_md5,
        payload_sha1=payload_sha1,
        payload_size=len(payload),
        ra_md5=special_ra_md5(data, platform),
    )


def nes_ra_hash(data: bytes) -> str:
    return hashlib.md5(nes_payload(data)).hexdigest()


def payload_for_platform(data: bytes, platform: Platform) -> bytes:
    mode = platform_spec(platform).hash_mode
    if mode == "nes":
        return nes_payload(data)
    if mode == "snes":
        return snes_payload(data)
    if mode == "n64":
        return n64_big_endian_payload(data)
    if mode == "fds":
        return fds_payload(data)
    if mode == "lynx":
        return lynx_payload(data)
    if mode == "a78":
        return a78_payload(data)
    if mode == "pce":
        return pce_payload(data)
    return data


def special_ra_md5(data: bytes, platform: Platform) -> str | None:
    """Hash RA que no coincide con el MD5 del payload (algoritmos rcheevos compuestos)."""
    if platform_spec(platform).hash_mode == "nds":
        assembled = nds_ra_payload(data)
        if assembled is not None:
            return hashlib.md5(assembled).hexdigest()
    return None


def arcade_ra_md5(set_name: str) -> str:
    """RetroAchievements hashea arcade por el nombre del set en minúsculas, no por contenido."""
    return hashlib.md5(set_name.lower().encode("utf-8")).hexdigest()


def nes_payload(data: bytes) -> bytes:
    return data[INES_HEADER_SIZE:] if data.startswith(b"NES\x1a") and len(data) > INES_HEADER_SIZE else data


def snes_payload(data: bytes) -> bytes:
    return data[SNES_COPIER_HEADER_SIZE:] if len(data) % 1024 == SNES_COPIER_HEADER_SIZE else data


def fds_payload(data: bytes) -> bytes:
    return data[FDS_HEADER_SIZE:] if data.startswith(b"FDS\x1a") and len(data) > FDS_HEADER_SIZE else data


def lynx_payload(data: bytes) -> bytes:
    return data[LYNX_HEADER_SIZE:] if data.startswith(b"LYNX\x00") and len(data) > LYNX_HEADER_SIZE else data


def a78_payload(data: bytes) -> bytes:
    return data[A78_HEADER_SIZE:] if len(data) > A78_HEADER_SIZE and data[1:10] == b"ATARI7800" else data


def pce_payload(data: bytes) -> bytes:
    return data[PCE_HEADER_SIZE:] if len(data) > PCE_HEADER_SIZE and len(data) % (128 * 1024) == PCE_HEADER_SIZE else data


def nds_ra_payload(data: bytes) -> bytes | None:
    """Reproduce el hash NDS de rcheevos: cabecera (0x160) + ARM9 + ARM7 + icono/título (0xA00)."""
    if len(data) < 0x160:
        return None
    arm9_offset = int.from_bytes(data[0x20:0x24], "little")
    arm9_size = int.from_bytes(data[0x2C:0x30], "little")
    arm7_offset = int.from_bytes(data[0x30:0x34], "little")
    arm7_size = int.from_bytes(data[0x3C:0x40], "little")
    icon_offset = int.from_bytes(data[0x68:0x6C], "little")
    parts = [data[0:0x160]]
    for offset, size in [(arm9_offset, arm9_size), (arm7_offset, arm7_size)]:
        if size > len(data) or offset > len(data) - size:
            return None
        parts.append(data[offset : offset + size])
    if icon_offset:
        if icon_offset > len(data) - 0xA00:
            return None
        parts.append(data[icon_offset : icon_offset + 0xA00])
    return b"".join(parts)


def n64_big_endian_payload(data: bytes) -> bytes:
    if len(data) < 4:
        return data
    magic = data[:4]
    if magic == b"\x80\x37\x12\x40":
        return data
    if magic == b"\x37\x80\x40\x12":
        return _swap_every(data, 2)
    if magic == b"\x40\x12\x37\x80":
        return _swap_every(data, 4)
    return data


def _swap_every(data: bytes, width: int) -> bytes:
    out = bytearray()
    limit = len(data) - (len(data) % width)
    for index in range(0, limit, width):
        out.extend(reversed(data[index : index + width]))
    out.extend(data[limit:])
    return bytes(out)
