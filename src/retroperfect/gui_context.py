"""Contexto compartido entre la cabecera y las pestañas de la GUI.

Cada pestaña recibe el contexto, registra en él los widgets y callbacks que
otras pestañas necesitan, y usa los que ya estén registrados solo en tiempo de
evento (nunca durante la construcción, salvo los de la cabecera).

Los campos se declaran con Protocols en vez de `Any`: lo que una pestaña usa de
un widget ajeno es siempre un trozo pequeño (`.value`, `.text`, `.rows`), y con
`Any` mypy no veía ni un nombre mal escrito ni una llamada con el número de
argumentos equivocado en toda la capa de interfaz. Los Protocols son
estructurales, así que los widgets de NiceGUI encajan sin heredar nada.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from nicegui import ui


class ValueControl(Protocol):
    """Widget con valor: input, select, checkbox, number..."""

    value: Any

    # NiceGUI devuelve el propio widget para poder encadenar, así que el
    # retorno va como Any en vez de None.
    def update(self) -> None: ...
    def set_value(self, value: Any) -> Any: ...
    def on_value_change(self, callback: Any) -> Any: ...


class SelectControl(ValueControl, Protocol):
    """Select, al que además se le reemplazan las opciones al cambiar de plataforma."""

    options: Any


class TextControl(Protocol):
    """Etiqueta o cualquier widget cuyo texto se reescribe."""

    text: str


class TableControl(Protocol):
    """Tabla de datos: se le cambian las filas y se refresca."""

    rows: list[dict[str, Any]]

    def update(self) -> None: ...


@dataclass
class UiContext:
    # Acciones registradas por la pestaña Plan e invocadas desde Resumen.
    summary_actions: dict[str, Callable[[], Awaitable[None]]] = field(default_factory=dict)
    # Widgets del setup consultados por los badges de la cabecera.
    header_refs: dict[str, ValueControl] = field(default_factory=dict)

    # Cabecera y pestañas (asigna build_ui).
    platform_select: SelectControl = None  # type: ignore[assignment]
    platform_tab: ui.tab = None  # type: ignore[assignment]
    setup_tab: ui.tab = None  # type: ignore[assignment]
    dats_tab: ui.tab = None  # type: ignore[assignment]
    profile_tab: ui.tab = None  # type: ignore[assignment]
    scan_tab: ui.tab = None  # type: ignore[assignment]
    verify_tab: ui.tab = None  # type: ignore[assignment]
    download_tab: ui.tab = None  # type: ignore[assignment]
    decisions_tab: ui.tab = None  # type: ignore[assignment]
    plan_tab: ui.tab = None  # type: ignore[assignment]
    summary_tab: ui.tab = None  # type: ignore[assignment]
    activity_tab: ui.tab = None  # type: ignore[assignment]

    # Callbacks de cabecera y control de acceso (asigna build_ui).
    refresh_header_status: Callable[[], None] = None  # type: ignore[assignment]
    update_tab_access: Callable[[], None] = None  # type: ignore[assignment]
    set_setup_ready: Callable[[bool], None] = None  # type: ignore[assignment]
    mark_setup_dirty: Callable[[], None] = None  # type: ignore[assignment]

    # Exportado por la pestaña Plataforma.
    platform_status: TextControl = None  # type: ignore[assignment]
    refresh_platform_cards: Callable[[], None] = None  # type: ignore[assignment]
    refresh_needed_table: Callable[[], None] = None  # type: ignore[assignment]

    # Exportado por Setup.
    source: ValueControl = None  # type: ignore[assignment]
    outdir: ValueControl = None  # type: ignore[assignment]
    arcade_mode: ValueControl = None  # type: ignore[assignment]
    dat: ValueControl = None  # type: ignore[assignment]
    dat_status: TextControl = None  # type: ignore[assignment]
    dat_source: SelectControl = None  # type: ignore[assignment]
    ra_cache_status: TextControl = None  # type: ignore[assignment]
    refresh_setup_platform_summary: Callable[[], None] = None  # type: ignore[assignment]

    # Exportado por Biblioteca DAT.
    online_table: TableControl = None  # type: ignore[assignment]
    dat_table: TableControl = None  # type: ignore[assignment]
    dat_manager_status: TextControl = None  # type: ignore[assignment]
    refresh_dat_table: Callable[[], None] = None  # type: ignore[assignment]

    # Exportado por Perfil: los widgets del perfil, por nombre
    # (ver `_profile_from_controls`, que es quien conoce las claves).
    controls: dict[str, ValueControl] = field(default_factory=dict)

    # Exportado por Escaneo.
    scan_status: TextControl = None  # type: ignore[assignment]

    # Exportado por Descargar.
    refresh_download_sources: Callable[[], None] = None  # type: ignore[assignment]

    # Exportado por Resumen y Decisiones.
    refresh_coverage: Callable[[], None] = None  # type: ignore[assignment]
    refresh_decisions: Callable[[], None] = None  # type: ignore[assignment]
