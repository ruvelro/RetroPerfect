"""Lectura de archivos .torrent, sin cliente ni red de por medio.

Un .torrent lleva dentro la lista completa de lo que contiene, así que sirve de
índice igual que el listado de archive.org o el directorio de un ZIP: se puede
planificar qué falta antes de descargar nada.

El formato es bencode, unas pocas reglas; se decodifica aquí en vez de añadir
una dependencia, que en este proyecto acaba pagándose al empaquetar binarios.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any

# Los .torrent de sets grandes rondan los pocos MB (el campo `pieces` manda).
# Por encima de esto es que no es un .torrent.
MAX_TORRENT_BYTES = 64 * 1024 * 1024


class TorrentError(ValueError):
    """El archivo no es un .torrent válido."""


class TorrentFile:
    """Un archivo dentro del torrent: ruta relativa y tamaño."""

    __slots__ = ("index", "length", "path")

    def __init__(self, index: int, path: str, length: int) -> None:
        self.index = index
        self.path = path
        self.length = length

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    def __repr__(self) -> str:
        return f"TorrentFile(index={self.index}, path={self.path!r}, length={self.length})"


class TorrentInfo:
    """Contenido de un .torrent: su nombre, la lista de archivos y su infohash."""

    def __init__(self, name: str, files: list[TorrentFile], piece_length: int, info_hash: str = "") -> None:
        self.name = name
        self.files = files
        self.piece_length = piece_length
        # Identifica el torrent ante cualquier cliente.
        self.info_hash = info_hash

    @property
    def total_size(self) -> int:
        return sum(item.length for item in self.files)


def read_torrent(path: Path) -> TorrentInfo:
    data = Path(path).read_bytes()
    if len(data) > MAX_TORRENT_BYTES:
        raise TorrentError(f"El archivo es demasiado grande para ser un .torrent ({len(data)} bytes).")
    spans: dict[bytes, tuple[int, int]] = {}
    decoded, _ = _decode_dict(data, 0, spans) if data[:1] == b"d" else (None, 0)
    if not isinstance(decoded, dict) or b"info" not in decoded:
        raise TorrentError("El archivo no contiene un diccionario 'info': no parece un .torrent.")
    info = _parse_info(decoded[b"info"], _text(decoded.get(b"encoding")) or "utf-8")
    # El infohash es el SHA1 del bloque `info` tal cual viene: se toma el rango
    # original en vez de re-serializar, que no siempre da byte a byte lo mismo.
    start, end = spans[b"info"]
    info.info_hash = hashlib.sha1(data[start:end]).hexdigest()
    return info


def _parse_info(info: Any, encoding: str) -> TorrentInfo:
    if not isinstance(info, dict):
        raise TorrentError("El bloque 'info' del .torrent está corrupto.")
    name = _text(info.get(b"name"), encoding) or "torrent"
    piece_length = int(info.get(b"piece length") or 0)

    if b"files" in info:
        files = []
        for index, entry in enumerate(info[b"files"]):
            if not isinstance(entry, dict):
                continue
            parts = [_text(part, encoding) for part in entry.get(b"path", [])]
            path = "/".join(part for part in parts if part)
            if path:
                files.append(TorrentFile(index=index, path=path, length=int(entry.get(b"length") or 0)))
        if not files:
            raise TorrentError("El .torrent no declara ningún archivo.")
        return TorrentInfo(name=name, files=files, piece_length=piece_length)

    # Torrent de un solo archivo: el nombre es el archivo.
    length = info.get(b"length")
    if length is None:
        raise TorrentError("El .torrent no declara ni 'files' ni 'length'.")
    return TorrentInfo(name=name, files=[TorrentFile(index=0, path=name, length=int(length))], piece_length=piece_length)


def _text(value: Any, encoding: str = "utf-8") -> str | None:
    if isinstance(value, bytes):
        return value.decode(encoding, errors="replace")
    if isinstance(value, str):
        return value
    return None


# --- bencode -----------------------------------------------------------------


def bdecode(data: bytes) -> Any:
    value, offset = _decode(data, 0)
    return value


def _decode(data: bytes, offset: int) -> tuple[Any, int]:
    if offset >= len(data):
        raise TorrentError("Datos bencode incompletos.")
    marker = data[offset : offset + 1]
    if marker == b"i":
        return _decode_int(data, offset)
    if marker == b"l":
        return _decode_list(data, offset)
    if marker == b"d":
        return _decode_dict(data, offset)
    if marker.isdigit():
        return _decode_bytes(data, offset)
    raise TorrentError(f"Marcador bencode inesperado {marker!r} en la posición {offset}.")


def _decode_int(data: bytes, offset: int) -> tuple[int, int]:
    end = data.find(b"e", offset)
    if end < 0:
        raise TorrentError("Entero bencode sin terminar.")
    try:
        return int(data[offset + 1 : end]), end + 1
    except ValueError as exc:
        raise TorrentError("Entero bencode inválido.") from exc


def _decode_bytes(data: bytes, offset: int) -> tuple[bytes, int]:
    separator = data.find(b":", offset)
    if separator < 0:
        raise TorrentError("Cadena bencode sin longitud.")
    try:
        length = int(data[offset:separator])
    except ValueError as exc:
        raise TorrentError("Longitud de cadena bencode inválida.") from exc
    start = separator + 1
    end = start + length
    if length < 0 or end > len(data):
        raise TorrentError("Cadena bencode más larga que los datos.")
    return data[start:end], end


def _decode_list(data: bytes, offset: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    offset += 1
    while offset < len(data) and data[offset : offset + 1] != b"e":
        value, offset = _decode(data, offset)
        items.append(value)
    if offset >= len(data):
        raise TorrentError("Lista bencode sin terminar.")
    return items, offset + 1


def _decode_dict(data: bytes, offset: int, spans: dict[bytes, tuple[int, int]] | None = None) -> tuple[dict[bytes, Any], int]:
    result: dict[bytes, Any] = {}
    offset += 1
    while offset < len(data) and data[offset : offset + 1] != b"e":
        key, offset = _decode(data, offset)
        value_start = offset
        value, offset = _decode(data, offset)
        if isinstance(key, bytes):
            result[key] = value
            if spans is not None:
                spans[key] = (value_start, offset)
    if offset >= len(data):
        raise TorrentError("Diccionario bencode sin terminar.")
    return result, offset + 1
