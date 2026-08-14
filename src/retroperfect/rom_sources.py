"""Fuentes de romsets configuradas por el usuario.

RetroPerfect no distribuye ROMs ni incluye catálogo de espejos: la app sabe qué
te falta y cómo verificarlo, pero el origen lo pone quien la usa. Cada fuente se
resuelve a una lista de RemoteFile; el emparejamiento con el DAT vive en
download_plan.py y la descarga en downloader.py.
"""
from __future__ import annotations

import json
import re
import zipfile
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Literal
from urllib.parse import quote, unquote, urljoin, urlsplit

from pydantic import BaseModel, Field

from .http import http_get
from .paths import config_dir, data_dir
from .remote_zip import HttpRangeReader

SourceKind = Literal["archive_org", "http_index", "local_dir", "zip_index"]

SOURCE_KIND_LABELS: dict[str, str] = {
    "archive_org": "Ítem de archive.org (trae hashes: verificación fiable)",
    "http_index": "Índice HTTP (autoíndice de Apache/nginx)",
    "local_dir": "Carpeta local o unidad de red montada",
    "zip_index": "ZIP con el set dentro, local o por URL (lee su índice sin bajarlo entero)",
}

# Los índices remotos cambian poco y algunos tienen miles de entradas: se cachean
# en disco para no re-descargarlos cada vez que se abre la pestaña.
INDEX_CACHE_TTL = timedelta(hours=12)

ARCHIVE_METADATA_URL = "https://archive.org/metadata/{item}"
ARCHIVE_DOWNLOAD_URL = "https://archive.org/download/{item}/{name}"

# Entradas que archive.org añade a cada ítem y que nunca son ROMs.
ARCHIVE_INTERNAL_FORMATS = {"Metadata", "Archive BitTorrent", "Item Tile", "JSON", "Log", "Text"}

_HREF_RE = re.compile(r"""<a\s[^>]*href\s*=\s*["']([^"']+)["']""", re.I)


class RomSource(BaseModel):
    id: str
    label: str
    kind: SourceKind
    location: str
    platform: str | None = None
    notes: str = ""
    enabled: bool = True


class RemoteFile(BaseModel):
    name: str
    url: str
    size: int | None = None
    crc32: str | None = None
    md5: str | None = None
    sha1: str | None = None
    # Cuando el archivo vive dentro de un contenedor, `url` apunta al contenedor
    # y esto a la ruta interna que hay que extraer.
    inner_path: str | None = None


class RemoteIndex(BaseModel):
    source_id: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    files: list[RemoteFile] = Field(default_factory=list)
    # De qué origen salió: si la fuente se reapunta a otro sitio, la caché deja
    # de valer aunque no haya expirado.
    kind: str = ""
    location: str = ""


def sources_path() -> Path:
    return config_dir() / "rom_sources.json"


def list_rom_sources(platform: str | None = None) -> list[RomSource]:
    path = sources_path()
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    sources = [RomSource.model_validate(row) for row in rows]
    if platform is None:
        return sources
    return [source for source in sources if source.platform in (None, platform)]


def save_rom_sources(sources: list[RomSource]) -> Path:
    path = sources_path()
    path.write_text(json.dumps([source.model_dump(mode="json") for source in sources], indent=2), encoding="utf-8")
    return path


def add_rom_source(source: RomSource) -> RomSource:
    sources = [item for item in list_rom_sources() if item.id != source.id]
    sources.append(source)
    save_rom_sources(sources)
    return source


def set_rom_source_enabled(source_id: str, enabled: bool) -> RomSource:
    """Activa o silencia una fuente sin perder su configuración (espejo caído, por ejemplo)."""
    sources = list_rom_sources()
    source = next((item for item in sources if item.id == source_id), None)
    if source is None:
        raise ValueError(f"Fuente de romsets desconocida: {source_id}")
    source.enabled = enabled
    save_rom_sources(sources)
    return source


def unique_source_id(base: str) -> str:
    """Evita que dos fuentes con el mismo nombre se pisen en silencio."""
    taken = {item.id for item in list_rom_sources()}
    if base not in taken:
        return base
    index = 2
    while f"{base}-{index}" in taken:
        index += 1
    return f"{base}-{index}"


def remove_rom_source(source_id: str) -> bool:
    sources = list_rom_sources()
    remaining = [item for item in sources if item.id != source_id]
    if len(remaining) == len(sources):
        return False
    save_rom_sources(remaining)
    index_cache_path(source_id).unlink(missing_ok=True)
    return True


def get_rom_source(source_id: str) -> RomSource:
    source = next((item for item in list_rom_sources() if item.id == source_id), None)
    if source is None:
        raise ValueError(f"Fuente de romsets desconocida: {source_id}")
    return source


def index_cache_dir() -> Path:
    path = data_dir() / "rom-index"
    path.mkdir(parents=True, exist_ok=True)
    return path


def index_cache_path(source_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in source_id)
    return index_cache_dir() / f"{safe}.json"


def resolve_source(source: RomSource, refresh: bool = False) -> RemoteIndex:
    """Devuelve el listado de archivos de la fuente, usando la caché en disco si sigue fresca."""
    cache = index_cache_path(source.id)
    if not refresh and cache.exists():
        try:
            cached = RemoteIndex.model_validate_json(cache.read_text(encoding="utf-8"))
        except ValueError:
            cached = None
        fresh = cached is not None and datetime.now(UTC) - cached.fetched_at < INDEX_CACHE_TTL
        same_origin = cached is not None and (cached.kind, cached.location) == (source.kind, source.location)
        if cached is not None and fresh and same_origin:
            return cached
    index = RemoteIndex(source_id=source.id, kind=source.kind, location=source.location, files=_fetch_files(source))
    cache.write_text(index.model_dump_json(indent=2), encoding="utf-8")
    return index


def _fetch_files(source: RomSource) -> list[RemoteFile]:
    if source.kind == "archive_org":
        return _fetch_archive_org(source.location)
    if source.kind == "http_index":
        return _fetch_http_index(source.location)
    if source.kind == "local_dir":
        return _fetch_local_dir(source.location)
    if source.kind == "zip_index":
        return _fetch_zip_index(source.location)
    raise ValueError(f"Tipo de fuente no soportado: {source.kind}")


def _fetch_archive_org(item: str) -> list[RemoteFile]:
    """El endpoint /metadata devuelve nombre, tamaño y md5/crc32/sha1 de cada archivo."""
    identifier = _archive_identifier(item)
    response = http_get(ARCHIVE_METADATA_URL.format(item=identifier))
    response.raise_for_status()
    payload = response.json()
    if not payload.get("files"):
        raise RuntimeError(f"El ítem de archive.org '{identifier}' no existe o no tiene archivos públicos.")
    files: list[RemoteFile] = []
    for entry in payload["files"]:
        name = entry.get("name") or ""
        if not name or entry.get("format") in ARCHIVE_INTERNAL_FORMATS or name.startswith(f"{identifier}_"):
            continue
        size = entry.get("size")
        files.append(
            RemoteFile(
                name=name,
                url=ARCHIVE_DOWNLOAD_URL.format(item=identifier, name=_quote_path(name)),
                size=int(size) if str(size).isdigit() else None,
                crc32=_clean_hash(entry.get("crc32")),
                md5=_clean_hash(entry.get("md5")),
                sha1=_clean_hash(entry.get("sha1")),
            )
        )
    return files


def _archive_identifier(item: str) -> str:
    """Acepta el identificador suelto o una URL de details/download."""
    if "://" not in item:
        return item.strip().strip("/")
    parts = [part for part in urlsplit(item).path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"details", "download", "metadata"}:
        return parts[1]
    return parts[-1] if parts else item


def _fetch_http_index(url: str) -> list[RemoteFile]:
    """Parsea un autoíndice de Apache/nginx: los <a href> que no son directorios ni el enlace al padre."""
    base = url if url.endswith("/") else f"{url}/"
    response = http_get(base)
    response.raise_for_status()
    files: list[RemoteFile] = []
    seen: set[str] = set()
    for href in _HREF_RE.findall(response.text):
        href = unescape(href)
        if href.startswith(("?", "#", "mailto:")) or href.endswith("/") or ".." in href:
            continue
        absolute = urljoin(base, href)
        if not absolute.startswith(base):
            continue
        name = unquote(Path(urlsplit(absolute).path).name)
        if not name or name in seen:
            continue
        seen.add(name)
        files.append(RemoteFile(name=name, url=absolute))
    return files


def _fetch_local_dir(location: str) -> list[RemoteFile]:
    root = Path(location).expanduser()
    if not root.is_dir():
        raise RuntimeError(f"La carpeta '{root}' no existe o no es accesible.")
    return [
        RemoteFile(name=path.name, url=str(path), size=path.stat().st_size)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.startswith(".")
    ]


def _fetch_zip_index(location: str) -> list[RemoteFile]:
    """Lista el contenido de un ZIP sin descargarlo entero.

    El directorio del ZIP guarda el CRC32 de cada entrada, así que el
    emparejamiento con el DAT sale por hash y no por nombre.
    """
    with _open_zip(location) as archive:
        return [
            RemoteFile(
                name=Path(info.filename).name,
                url=location,
                inner_path=info.filename,
                size=info.file_size,
                crc32=f"{info.CRC & 0xFFFFFFFF:08x}",
            )
            for info in archive.infolist()
            if not info.is_dir() and not Path(info.filename).name.startswith(".")
        ]


def _open_zip(location: str) -> zipfile.ZipFile:
    if "://" in location and not location.startswith("file://"):
        return zipfile.ZipFile(HttpRangeReader(location))  # type: ignore[arg-type]
    path = Path(location[7:] if location.startswith("file://") else location).expanduser()
    if not path.is_file():
        raise RuntimeError(f"El archivo ZIP '{path}' no existe o no es accesible.")
    return zipfile.ZipFile(path)


def read_zip_member(location: str, inner_path: str) -> bytes:
    """Extrae un miembro concreto; en remoto solo se piden sus bytes."""
    with _open_zip(location) as archive, archive.open(inner_path) as member:
        return member.read()


def _quote_path(name: str) -> str:
    return quote(name)


def _clean_hash(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower()
