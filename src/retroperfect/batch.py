"""Curar un romset de varios sistemas en una sola pasada.

Todo el flujo asumía una plataforma por comando, así que una colección con nueve
sistemas eran nueve invocaciones con sus nueve rutas y sus nueve DAT. Esto
recorre las carpetas de un romset, deduce la plataforma de cada una, busca el
DAT instalado que le corresponde y hace el trabajo de siempre con cada una.

No hay lógica nueva de curación: se reutilizan el escaneo, el perfil y el plan.
Lo que aporta es el recorrido y, sobre todo, **decir qué carpeta se ha saltado y
por qué**: una carpeta cuyo nombre no se reconoce o que no tiene DAT instalado
se reporta en vez de curarse a medias o con el DAT equivocado.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .dat_manager import list_installed_dats
from .models import Platform
from .platforms import platform_from_folder_name


class BatchTarget(BaseModel):
    """Una carpeta del romset y lo que se puede hacer con ella."""

    folder: str
    platform: str = ""
    platform_label: str = ""
    dat: str = ""
    dat_name: str = ""
    skipped_reason: str = ""

    @property
    def name(self) -> str:
        return Path(self.folder).name

    @property
    def can_curate(self) -> bool:
        return not self.skipped_reason


class BatchOutcome(BaseModel):
    """Resultado de curar una carpeta."""

    target: BatchTarget
    roms: int = 0
    matched: int = 0
    kept: int = 0
    applied: int = 0
    manifest: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def discover_targets(root: Path, only: set[Platform] | None = None) -> list[BatchTarget]:
    """Carpetas del romset con la plataforma y el DAT que les corresponden.

    Se miran solo las subcarpetas directas: es como está organizado un romset
    multi-sistema, y bajar más haría pasar por plataforma cada carpeta de
    región o de letra.
    """
    dats = _dats_by_platform()
    objetivos: list[BatchTarget] = []
    for carpeta in sorted(item for item in root.iterdir() if item.is_dir()):
        objetivo = BatchTarget(folder=str(carpeta))
        platform = platform_from_folder_name(carpeta.name)
        if platform is None:
            objetivo.skipped_reason = "No se reconoce a qué plataforma corresponde el nombre de la carpeta."
            objetivos.append(objetivo)
            continue
        objetivo.platform = platform.value
        objetivo.platform_label = _label(platform)
        if only is not None and platform not in only:
            objetivo.skipped_reason = "Fuera de las plataformas pedidas."
            objetivos.append(objetivo)
            continue
        elegido = dats.get(platform)
        if elegido is None:
            objetivo.skipped_reason = f"No hay ningún DAT de {_label(platform)} instalado. Descárgalo con dat-download."
            objetivos.append(objetivo)
            continue
        objetivo.dat, objetivo.dat_name = elegido
        objetivos.append(objetivo)
    return objetivos


def _dats_by_platform() -> dict[Platform, tuple[str, str]]:
    """DAT instalado de cada plataforma: (ruta, nombre), prefiriendo el recomendado."""
    elegidos: dict[Platform, tuple[str, str]] = {}
    for dat in sorted(list_installed_dats(), key=lambda item: (not item.recommended, item.name)):
        if not dat.platform:
            continue
        try:
            platform = Platform(dat.platform)
        except ValueError:
            continue  # un DAT de una plataforma que ya no existe en el catálogo
        elegidos.setdefault(platform, (dat.path, dat.name))
    return elegidos


def _label(platform: Platform) -> str:
    from .platforms import platform_spec

    return platform_spec(platform).short_name


class BatchReport(BaseModel):
    root: str
    outcomes: list[BatchOutcome] = Field(default_factory=list)
    skipped: list[BatchTarget] = Field(default_factory=list)

    @property
    def curated(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.ok)

    @property
    def failed(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.ok)

    @property
    def total_kept(self) -> int:
        return sum(outcome.kept for outcome in self.outcomes)
