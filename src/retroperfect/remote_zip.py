"""Lectura de un ZIP remoto sin descargarlo entero.

El índice de un ZIP (el central directory) vive al final del archivo, así que
con unas pocas peticiones de rango se obtiene la lista completa de lo que
contiene y, después, solo los bytes del miembro que interesa. Eso convierte un
ZIP de cientos de gigas en una fuente utilizable.

En vez de parsear el formato a mano se expone un archivo seekable sobre HTTP y
se le entrega a zipfile, que ya sabe de ZIP64, codificaciones y casos raros.
"""
from __future__ import annotations

import io
import re

from .http import DEFAULT_TIMEOUT_SECONDS, session

# zipfile hace muchas lecturas pequeñas al recorrer el directorio: se traen en
# bloques para no convertir cada una en una petición HTTP.
BLOCK_SIZE = 256 * 1024

CONTENT_RANGE_TOTAL = re.compile(r"/(\d+)\s*$")


class RangeNotSupportedError(RuntimeError):
    """El servidor no sirve rangos, así que no se puede leer el ZIP por partes."""


class HttpRangeReader(io.RawIOBase):
    """Archivo de solo lectura y seekable respaldado por peticiones Range."""

    def __init__(self, url: str, block_size: int = BLOCK_SIZE) -> None:
        self.url = url
        self.block_size = block_size
        self._pos = 0
        self._cache_start = 0
        self._cache = b""
        self.size = self._probe()

    def _probe(self) -> int:
        """Confirma que hay soporte de rangos y averigua el tamaño total."""
        response = session().get(self.url, headers={"Range": "bytes=0-0"}, timeout=DEFAULT_TIMEOUT_SECONDS)
        response.close()
        if response.status_code != 206:
            raise RangeNotSupportedError(
                f"El servidor no admite descargas parciales (código {response.status_code}). "
                "Sin eso habría que descargar el ZIP completo para poder leerlo."
            )
        match = CONTENT_RANGE_TOTAL.search(response.headers.get("content-range", ""))
        if not match:
            raise RangeNotSupportedError("El servidor no informa del tamaño total del archivo (falta Content-Range).")
        return int(match.group(1))

    def _fetch(self, start: int, length: int) -> bytes:
        end = min(start + length, self.size) - 1
        if end < start:
            return b""
        response = session().get(self.url, headers={"Range": f"bytes={start}-{end}"}, timeout=DEFAULT_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.content

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        elif whence == io.SEEK_END:
            self._pos = self.size + offset
        else:
            raise ValueError(f"Modo de seek no soportado: {whence}")
        self._pos = max(0, min(self._pos, self.size))
        return self._pos

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self.size - self._pos
        size = min(size, self.size - self._pos)
        if size <= 0:
            return b""
        if not self._cached(self._pos, size):
            block = max(size, self.block_size)
            self._cache_start = self._pos
            self._cache = self._fetch(self._pos, block)
        offset = self._pos - self._cache_start
        data = self._cache[offset : offset + size]
        self._pos += len(data)
        return data

    def readinto(self, buffer) -> int:  # type: ignore[override]
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def _cached(self, start: int, size: int) -> bool:
        return self._cache_start <= start and start + size <= self._cache_start + len(self._cache)
