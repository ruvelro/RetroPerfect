"""Lectura de imágenes CHD de CD vía chdimage (binding de chd-rs en Rust).

Cubre los CHD creados con `chdman createcd`: sha1 por pista (los mismos que
listan los DAT de Redump, sin el padding que añade chdman) y acceso por
sectores para los hashes de RetroAchievements. Los CHD de GDI (Dreamcast),
DVD y disco duro los rechaza el propio lector; en esos casos las funciones
degradan a None/DiscError en vez de romper el escaneo."""
from __future__ import annotations

from pathlib import Path

from .disc import RAW_SYNC, SECTOR_USER_SIZE, DiscError, Iso9660Image

try:
    import chdimage
except ImportError:  # plataforma sin wheel de chdimage: se degrada con aviso
    chdimage = None  # type: ignore[assignment]

# chdimage direcciona en LBA absolutos de CD, que incluyen los 150 sectores
# (2 segundos) de pregap: el sector 0 de datos está en la posición 150.
CD_PREGAP_SECTORS = 150


def chd_available() -> bool:
    return chdimage is not None


def chd_track_sha1s(path: Path) -> list[str] | None:
    """Sha1 hex de cada pista del CHD, o None si no se puede leer."""
    if chdimage is None:
        return None
    try:
        chd = chdimage.open(str(path))
        return [bytes(digest).hex() for digest in chd.track_sha1s()]
    except Exception:
        return None


class ChdDiscImage(Iso9660Image):
    """Acceso ISO9660 a la pista de datos de un CHD de CD."""

    def __init__(self, path: Path):
        if chdimage is None:
            raise DiscError("Soporte CHD no disponible: falta el paquete chdimage.")
        self.path = path
        try:
            self._chd = chdimage.open(str(path))
        except Exception as error:
            raise DiscError(f"No se pudo abrir el CHD: {error}") from None
        self.base_lba = 0
        self._position: int | None = None
        self.user_offset = self._detect_layout()

    def _read_raw(self, lba: int) -> bytes:
        target = lba + CD_PREGAP_SECTORS
        try:
            if self._position != target:
                self._chd.set_location(chdimage.MsfIndex.from_lba(target))
            sector = bytes(self._chd.copy_current_sector())
            # avanzar ya deja el lector listo para el sector siguiente, que es
            # el caso común (read_extent lee extents contiguos).
            self._chd.advance_position()
        except Exception as error:
            self._position = None
            raise DiscError(f"Lectura fuera del CHD (LBA {lba}): {error}") from None
        self._position = target + 1
        return sector

    def _detect_layout(self) -> int:
        head = self._read_raw(self.base_lba)
        if head[:12] == RAW_SYNC:
            mode = head[15]
            if mode == 1:
                return 16
            if mode == 2:
                return 24  # MODE2/XA form 1
            raise DiscError(f"Modo de sector raw no soportado: {mode}")
        return 0

    def read_user_sector(self, lba: int) -> bytes:
        sector = self._read_raw(lba)
        return sector[self.user_offset : self.user_offset + SECTOR_USER_SIZE]
