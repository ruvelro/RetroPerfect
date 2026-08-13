from __future__ import annotations

import binascii
import hashlib

from .models import Platform, RomHash
from .platforms import platform_spec


INES_HEADER_SIZE = 16
SNES_COPIER_HEADER_SIZE = 512
HASH_CHUNK_SIZE = 1024 * 1024


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
        ra_hash=md5_hex,
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
        ra_hash=payload_md5,
        payload_crc32=payload_crc32,
        payload_md5=payload_md5,
        payload_sha1=payload_sha1,
        payload_size=len(payload),
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
    return data


def nes_payload(data: bytes) -> bytes:
    return data[INES_HEADER_SIZE:] if data.startswith(b"NES\x1a") and len(data) > INES_HEADER_SIZE else data


def snes_payload(data: bytes) -> bytes:
    return data[SNES_COPIER_HEADER_SIZE:] if len(data) % 1024 == SNES_COPIER_HEADER_SIZE else data


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
