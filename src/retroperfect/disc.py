"""Lector mínimo de imágenes de disco (ISO 2048 y BIN/CUE 2352) con ISO9660,
suficiente para calcular los hashes de RetroAchievements de PSX, Sega CD/Saturn y PSP.
CHD, GDI multipista y CDI no están soportados todavía."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

SECTOR_USER_SIZE = 2048
RAW_SECTOR_SIZE = 2352
RAW_SYNC = b"\x00" + b"\xff" * 10 + b"\x00"


class DiscError(Exception):
    pass


class DiscImage:
    """Acceso por sectores de datos (2048 bytes de usuario) sobre .iso, .bin o .cue."""

    def __init__(self, path: Path):
        if path.suffix.lower() == ".cue":
            path = _data_file_from_cue(path)
        self.path = path
        self.handle = path.open("rb")
        self.sector_size, self.user_offset = self._detect_layout()

    def close(self) -> None:
        self.handle.close()

    def __enter__(self) -> DiscImage:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _detect_layout(self) -> tuple[int, int]:
        self.handle.seek(0)
        head = self.handle.read(16)
        if len(head) < 16:
            raise DiscError("Imagen demasiado pequeña.")
        if head[:12] == RAW_SYNC:
            mode = head[15]
            if mode == 1:
                return RAW_SECTOR_SIZE, 16
            if mode == 2:
                return RAW_SECTOR_SIZE, 24  # MODE2/XA form 1
            raise DiscError(f"Modo de sector raw no soportado: {mode}")
        return SECTOR_USER_SIZE, 0

    def read_user_sector(self, index: int) -> bytes:
        self.handle.seek(index * self.sector_size + self.user_offset)
        return self.handle.read(SECTOR_USER_SIZE)

    def read_extent(self, sector: int, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        index = sector
        while remaining > 0:
            data = self.read_user_sector(index)
            if not data:
                raise DiscError("Lectura fuera de la imagen.")
            chunks.append(data[: min(remaining, SECTOR_USER_SIZE)])
            remaining -= SECTOR_USER_SIZE
            index += 1
        return b"".join(chunks)

    # --- ISO9660 ---

    def root_directory(self) -> tuple[int, int]:
        pvd = self.read_user_sector(16)
        if len(pvd) < 190 or pvd[1:6] != b"CD001":
            raise DiscError("No se encontró el descriptor de volumen ISO9660.")
        record = pvd[156 : 156 + 34]
        return int.from_bytes(record[2:6], "little"), int.from_bytes(record[10:14], "little")

    def list_directory(self, sector: int, size: int) -> dict[str, tuple[int, int, bool]]:
        """Devuelve {nombre: (sector, tamaño, es_directorio)} con nombres sin ';1' en mayúsculas."""
        entries: dict[str, tuple[int, int, bool]] = {}
        data = self.read_extent(sector, size)
        offset = 0
        while offset < len(data):
            length = data[offset]
            if length == 0:
                # los registros no cruzan sectores: saltar al siguiente
                offset = (offset // SECTOR_USER_SIZE + 1) * SECTOR_USER_SIZE
                continue
            record = data[offset : offset + length]
            name_length = record[32]
            raw_name = record[33 : 33 + name_length]
            offset += length
            if raw_name in (b"\x00", b"\x01"):
                continue
            name = raw_name.decode("ascii", errors="replace").split(";")[0].upper()
            entries[name] = (
                int.from_bytes(record[2:6], "little"),
                int.from_bytes(record[10:14], "little"),
                bool(record[25] & 0x02),
            )
        return entries

    def find_file(self, path: str) -> tuple[int, int]:
        sector, size = self.root_directory()
        components = [part for part in re.split(r"[\\/]", path) if part]
        for index, component in enumerate(components):
            entries = self.list_directory(sector, size)
            entry = entries.get(component.split(";")[0].upper())
            if entry is None:
                raise DiscError(f"No existe {component} en la imagen.")
            sector, size, is_dir = entry
            if index < len(components) - 1 and not is_dir:
                raise DiscError(f"{component} no es un directorio.")
        return sector, size

    def read_file(self, path: str) -> bytes:
        sector, size = self.find_file(path)
        return self.read_extent(sector, size)


def _data_file_from_cue(cue_path: Path) -> Path:
    text = cue_path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'FILE\s+"([^"]+)"', text, re.I) or re.search(r"FILE\s+(\S+)", text, re.I)
    if not match:
        raise DiscError("CUE sin entrada FILE.")
    candidate = cue_path.parent / match.group(1)
    if not candidate.exists():
        raise DiscError(f"El CUE apunta a {match.group(1)}, que no existe.")
    return candidate


def psx_ra_md5(disc: DiscImage) -> str:
    """rcheevos: MD5 del nombre del ejecutable (según SYSTEM.CNF) + su contenido."""
    exe_name = "PSX.EXE"
    try:
        cnf = disc.read_file("SYSTEM.CNF").decode("ascii", errors="replace")
        match = re.search(r"BOOT\s*=\s*cdrom:?[\\/]*([^\s]+)", cnf, re.I)
        if match:
            exe_name = match.group(1).strip()
    except DiscError:
        pass
    exe = disc.read_file(exe_name)
    if exe[:8] == b"PS-X EXE":
        size = int.from_bytes(exe[28:32], "little") + 2048
        exe = exe[:size]
    digest = hashlib.md5()
    digest.update(exe_name.encode("ascii", errors="replace"))
    digest.update(exe)
    return digest.hexdigest()


def segacd_ra_md5(disc: DiscImage) -> str:
    """rcheevos: MD5 de los primeros 512 bytes del sector 0 (cabecera del disco).
    Vale tanto para Sega CD como para Saturn."""
    return hashlib.md5(disc.read_user_sector(0)[:512]).hexdigest()


def psp_ra_md5(disc: DiscImage) -> str:
    """rcheevos: MD5 de PSP_GAME/PARAM.SFO + PSP_GAME/SYSDIR/EBOOT.BIN."""
    digest = hashlib.md5()
    digest.update(disc.read_file("PSP_GAME/PARAM.SFO"))
    digest.update(disc.read_file("PSP_GAME/SYSDIR/EBOOT.BIN"))
    return digest.hexdigest()


DISC_RA_MODES = {"psx", "segacd", "psp"}
DISC_RA_SUFFIXES = {".cue", ".iso", ".bin"}


def disc_ra_md5(path: Path, hash_mode: str) -> str | None:
    """Hash RA de una imagen de disco, o None si el formato/estructura no lo permite."""
    if hash_mode not in DISC_RA_MODES or path.suffix.lower() not in DISC_RA_SUFFIXES:
        return None
    try:
        with DiscImage(path) as disc:
            if hash_mode == "psx":
                return psx_ra_md5(disc)
            if hash_mode == "segacd":
                return segacd_ra_md5(disc)
            return psp_ra_md5(disc)
    except (OSError, DiscError):
        return None
