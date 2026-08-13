from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests

from .paths import data_dir
from .platforms import list_platforms


@dataclass(frozen=True)
class DatSource:
    id: str
    platform: str
    label: str
    format: str
    url: str
    filename: str
    notes: str
    direct_download: bool = True


def _build_dat_sources() -> list[DatSource]:
    sources: list[DatSource] = []
    for spec in list_platforms():
        primary_alias = spec.dat_aliases[0]
        filename = f"{primary_alias}.dat"
        if spec.dat_family == "nointro":
            sources.append(
                DatSource(
                    id=f"libretro-{spec.id.value}-nointro",
                    platform=spec.id.value,
                    label=f"{spec.short_name} - No-Intro mirror",
                    format="clrmamepro",
                    url=f"https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/no-intro/{quote(filename)}",
                    filename=filename,
                    notes=f"Espejo publico Libretro. Recomendado: {spec.dat_recommended}.",
                )
            )
            sources.append(
                DatSource(
                    id=f"nointro-datomatic-{spec.id.value}",
                    platform=spec.id.value,
                    label=f"{spec.short_name} - DAT-o-MATIC oficial",
                    format="P/C XML o Standard DAT",
                    url="https://datomatic.no-intro.org/index.php?page=download",
                    filename=f"No-Intro DAT-o-MATIC - {spec.short_name}.zip",
                    notes=f"Fuente oficial. Selecciona {primary_alias} y, si existe, Parent/Clone XML.",
                    direct_download=False,
                )
            )
        elif spec.dat_family == "redump":
            sources.append(
                DatSource(
                    id=f"redump-{spec.id.value}",
                    platform=spec.id.value,
                    label=f"{spec.short_name} - Redump/Non-Redump manual",
                    format="DAT de discos",
                    url="http://redump.org/downloads/",
                    filename=f"Redump - {spec.short_name}.dat",
                    notes="Sistemas de disco: usa DAT de la misma variante/formato. Descarga/importacion manual asistida.",
                    direct_download=False,
                )
            )
            sources.append(
                DatSource(
                    id=f"nointro-nonredump-{spec.id.value}",
                    platform=spec.id.value,
                    label=f"{spec.short_name} - DAT-o-MATIC Non-Redump",
                    format="Non-Redump DAT",
                    url="https://datomatic.no-intro.org/index.php?page=download",
                    filename=f"Non-Redump - {spec.short_name}.zip",
                    notes=f"Si existe en DAT-o-MATIC, busca {primary_alias}.",
                    direct_download=False,
                )
            )
        elif spec.dat_family in {"mame", "fbneo", "arcade"}:
            if spec.dat_family in {"mame", "arcade"}:
                sources.append(
                    DatSource(
                        id=f"mame-{spec.id.value}",
                        platform=spec.id.value,
                        label=f"{spec.short_name} - MAME XML/DAT",
                        format="MAME XML / Logiqx",
                        url="https://www.mamedev.org/release.html",
                        filename=f"MAME - {spec.short_name}.xml",
                        notes="Arcade depende de version exacta, parents, clones, BIOS, devices y CHD. Importa el XML/DAT de tu version.",
                        direct_download=False,
                    )
                )
            if spec.dat_family in {"fbneo", "arcade"}:
                sources.append(
                    DatSource(
                        id=f"fbneo-{spec.id.value}",
                        platform=spec.id.value,
                        label=f"{spec.short_name} - FBNeo DAT",
                        format="FBNeo DAT",
                        url="https://github.com/libretro/FBNeo/tree/master/dats",
                        filename=f"FBNeo - {spec.short_name}.dat",
                        notes="Usa el DAT que corresponda al core/version FBNeo exacto; no mezclar con MAME sin reconstruir.",
                        direct_download=False,
                    )
                )
        else:
            sources.append(
                DatSource(
                    id=f"manual-{spec.id.value}",
                    platform=spec.id.value,
                    label=f"{spec.short_name} - DAT manual",
                    format=spec.dat_recommended,
                    url="",
                    filename=filename,
                    notes="Fuente no automatizada todavia. Importa un DAT compatible desde Biblioteca DAT.",
                    direct_download=False,
                )
            )
    return sources


DAT_SOURCES = _build_dat_sources()


def dat_download_dir() -> Path:
    path = data_dir() / "dats"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_dat_sources(platform: str = "nes") -> list[DatSource]:
    return [source for source in DAT_SOURCES if source.platform == platform]


def download_dat(source_id: str) -> Path:
    source = next((item for item in DAT_SOURCES if item.id == source_id), None)
    if source is None:
        raise ValueError(f"Unknown DAT source: {source_id}")
    if not source.direct_download:
        raise RuntimeError(f"{source.label} is not a direct download URL. Open it in a browser and import the downloaded ZIP.")
    return download_url(source.url, source.filename)


def download_url(url: str, filename: str | None = None) -> Path:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    if filename is None:
        filename = _filename_from_response(url, response.headers.get("content-disposition"))
    path = dat_download_dir() / "downloads" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return path


def _filename_from_response(url: str, content_disposition: str | None) -> str:
    if content_disposition and "filename=" in content_disposition:
        return content_disposition.split("filename=", 1)[1].strip().strip('"')
    name = Path(url.split("?", 1)[0]).name
    return name or "downloaded-dat.dat"
