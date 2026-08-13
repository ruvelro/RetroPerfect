from __future__ import annotations

import binascii
import hashlib
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from .paths import data_dir

SUPPORTED_PATCH_EXTENSIONS = {".ips", ".bps", ".ups", ".xdelta", ".vcdiff"}
KNOWN_UNSUPPORTED_PATCH_EXTENSIONS = {".ppf", ".aps", ".rup"}


@dataclass(frozen=True)
class PatchPayload:
    name: str
    suffix: str
    data: bytes


def patch_cache_dir() -> Path:
    path = data_dir() / "patches"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_patch(url: str) -> Path:
    parsed = urlparse(url)
    filename = Path(parsed.path).name or "patch"
    url_key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    destination = patch_cache_dir() / url_key / filename
    if destination.exists():
        return destination
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination


def load_patch_payload(path: Path) -> PatchPayload:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_PATCH_EXTENSIONS:
        return PatchPayload(path.name, suffix, path.read_bytes())
    if suffix == ".zip":
        return _load_patch_from_zip(path)
    if suffix in KNOWN_UNSUPPORTED_PATCH_EXTENSIONS:
        raise ValueError(f"Formato de parche no soportado todavía: {suffix}")
    raise ValueError(f"No se encontró un parche soportado en {path.name}")


def apply_patch_bytes(source: bytes, patch: PatchPayload) -> bytes:
    if patch.suffix == ".ips":
        return apply_ips(source, patch.data)
    if patch.suffix == ".bps":
        return apply_bps(source, patch.data)
    if patch.suffix == ".ups":
        return apply_ups(source, patch.data)
    if patch.suffix in {".xdelta", ".vcdiff"}:
        return apply_xdelta(source, patch.data)
    raise ValueError(f"Formato de parche no soportado: {patch.suffix}")


def download_and_apply_patch(source: bytes, patch_url: str) -> tuple[bytes, PatchPayload]:
    patch_path = download_patch(patch_url)
    patch = load_patch_payload(patch_path)
    return apply_patch_bytes(source, patch), patch


def _load_patch_from_zip(path: Path) -> PatchPayload:
    with zipfile.ZipFile(path) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        supported = [info for info in infos if Path(info.filename).suffix.lower() in SUPPORTED_PATCH_EXTENSIONS]
        if supported:
            chosen = sorted(supported, key=lambda info: info.filename.lower())[0]
            return PatchPayload(Path(chosen.filename).name, Path(chosen.filename).suffix.lower(), archive.read(chosen))
        unsupported = [info for info in infos if Path(info.filename).suffix.lower() in KNOWN_UNSUPPORTED_PATCH_EXTENSIONS]
        if unsupported:
            suffix = Path(unsupported[0].filename).suffix.lower()
            raise ValueError(f"El ZIP contiene parche {suffix}, pero ese formato no está soportado todavía.")
    raise ValueError("El ZIP no contiene parches IPS/BPS.")


def apply_ips(source: bytes, patch: bytes) -> bytes:
    if not patch.startswith(b"PATCH"):
        raise ValueError("IPS inválido: cabecera PATCH no encontrada.")
    output = bytearray(source)
    index = 5
    while True:
        if patch[index : index + 3] == b"EOF":
            index += 3
            if len(patch) - index >= 3:
                truncate = int.from_bytes(patch[index : index + 3], "big")
                output = output[:truncate]
            return bytes(output)
        if index + 5 > len(patch):
            raise ValueError("IPS inválido: registro incompleto.")
        offset = int.from_bytes(patch[index : index + 3], "big")
        index += 3
        size = int.from_bytes(patch[index : index + 2], "big")
        index += 2
        if size == 0:
            if index + 3 > len(patch):
                raise ValueError("IPS inválido: registro RLE incompleto.")
            rle_size = int.from_bytes(patch[index : index + 2], "big")
            value = patch[index + 2]
            index += 3
            data = bytes([value]) * rle_size
        else:
            if index + size > len(patch):
                raise ValueError("IPS inválido: datos incompletos.")
            data = patch[index : index + size]
            index += size
        end = offset + len(data)
        if end > len(output):
            output.extend(b"\0" * (end - len(output)))
        output[offset:end] = data


def apply_ups(source: bytes, patch: bytes) -> bytes:
    if not patch.startswith(b"UPS1"):
        raise ValueError("UPS inválido: cabecera UPS1 no encontrada.")
    if len(patch) < 4 + 12:
        raise ValueError("UPS inválido: demasiado pequeño.")
    patch_crc_expected = struct.unpack("<I", patch[-4:])[0]
    if (binascii.crc32(patch[:-4]) & 0xFFFFFFFF) != patch_crc_expected:
        raise ValueError("UPS inválido: CRC del parche no coincide.")
    source_crc_expected, target_crc_expected = struct.unpack("<II", patch[-12:-4])
    if (binascii.crc32(source) & 0xFFFFFFFF) != source_crc_expected:
        raise ValueError("UPS no aplicable: CRC de ROM origen no coincide.")

    reader = _BpsReader(patch[4:-12])
    source_size = reader.read_number()
    target_size = reader.read_number()
    if len(source) != source_size:
        raise ValueError("UPS no aplicable: tamaño de ROM origen no coincide.")

    output = bytearray(target_size)
    output[: min(source_size, target_size)] = source[:target_size]
    pointer = 0
    while reader.index < len(reader.data):
        pointer += reader.read_number()
        while True:
            byte = reader.read(1)[0]
            if byte == 0:
                pointer += 1
                break
            if pointer < target_size:
                output[pointer] ^= byte
            pointer += 1
    result = bytes(output)
    if (binascii.crc32(result) & 0xFFFFFFFF) != target_crc_expected:
        raise ValueError("UPS aplicado, pero CRC final no coincide.")
    return result


def apply_xdelta(source: bytes, patch: bytes) -> bytes:
    import tempfile

    import pyxdelta

    with tempfile.TemporaryDirectory(prefix="retroperfect-xdelta-") as workdir:
        base = Path(workdir)
        source_path = base / "source.bin"
        patch_path = base / "patch.xdelta"
        output_path = base / "output.bin"
        source_path.write_bytes(source)
        patch_path.write_bytes(patch)
        if not pyxdelta.decode(str(source_path), str(patch_path), str(output_path)):
            raise ValueError("xdelta no aplicable: el parche no corresponde a esta ROM.")
        return output_path.read_bytes()


def apply_bps(source: bytes, patch: bytes) -> bytes:
    if not patch.startswith(b"BPS1"):
        raise ValueError("BPS inválido: cabecera BPS1 no encontrada.")
    if len(patch) < 16:
        raise ValueError("BPS inválido: demasiado pequeño.")
    patch_crc_expected = struct.unpack("<I", patch[-4:])[0]
    if (binascii.crc32(patch[:-4]) & 0xFFFFFFFF) != patch_crc_expected:
        raise ValueError("BPS inválido: CRC del parche no coincide.")
    source_crc_expected, target_crc_expected = struct.unpack("<II", patch[-12:-4])
    if (binascii.crc32(source) & 0xFFFFFFFF) != source_crc_expected:
        raise ValueError("BPS no aplicable: CRC de ROM origen no coincide.")

    reader = _BpsReader(patch[4:-12])
    source_size = reader.read_number()
    target_size = reader.read_number()
    metadata_size = reader.read_number()
    reader.skip(metadata_size)
    if source_size != len(source):
        raise ValueError("BPS no aplicable: tamaño de ROM origen no coincide.")

    target = bytearray()
    source_relative_offset = 0
    target_relative_offset = 0
    while len(target) < target_size:
        command = reader.read_number()
        action = command & 3
        length = (command >> 2) + 1
        if action == 0:
            target.extend(source[len(target) : len(target) + length])
        elif action == 1:
            target.extend(reader.read(length))
        elif action == 2:
            source_relative_offset += reader.read_signed_number()
            target.extend(source[source_relative_offset : source_relative_offset + length])
            source_relative_offset += length
        elif action == 3:
            target_relative_offset += reader.read_signed_number()
            for _ in range(length):
                target.append(target[target_relative_offset])
                target_relative_offset += 1
    result = bytes(target)
    if (binascii.crc32(result) & 0xFFFFFFFF) != target_crc_expected:
        raise ValueError("BPS aplicado, pero CRC final no coincide.")
    return result


class _BpsReader:
    def __init__(self, data: bytes):
        self.data = data
        self.index = 0

    def read(self, size: int) -> bytes:
        if self.index + size > len(self.data):
            raise ValueError("BPS inválido: lectura fuera de rango.")
        chunk = self.data[self.index : self.index + size]
        self.index += size
        return chunk

    def skip(self, size: int) -> None:
        self.read(size)

    def read_number(self) -> int:
        data = 0
        shift = 1
        while True:
            byte = self.read(1)[0]
            data += (byte & 0x7F) * shift
            if byte & 0x80:
                break
            shift <<= 7
            data += shift
        return data

    def read_signed_number(self) -> int:
        value = self.read_number()
        signed = value >> 1
        return -signed if value & 1 else signed
