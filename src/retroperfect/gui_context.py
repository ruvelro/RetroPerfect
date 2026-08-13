"""Contexto compartido entre la cabecera y las pestañas de la GUI.

Cada pestaña recibe el contexto, registra en él los widgets y callbacks que
otras pestañas necesitan, y usa los que ya estén registrados solo en tiempo de
evento (nunca durante la construcción, salvo los de la cabecera).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UiContext:
    # Acciones registradas por la pestaña Plan e invocadas desde Resumen.
    summary_actions: dict[str, Callable[[], Awaitable[None]]] = field(default_factory=dict)
    # Widgets del setup consultados por los badges de la cabecera.
    header_refs: dict[str, Any] = field(default_factory=dict)

    # Cabecera y pestañas (asigna build_ui).
    platform_select: Any = None
    platform_tab: Any = None
    setup_tab: Any = None
    dats_tab: Any = None
    profile_tab: Any = None
    scan_tab: Any = None
    verify_tab: Any = None
    decisions_tab: Any = None
    plan_tab: Any = None
    summary_tab: Any = None
    activity_tab: Any = None

    # Callbacks de cabecera y control de acceso (asigna build_ui).
    refresh_header_status: Any = None
    update_tab_access: Any = None
    set_setup_ready: Any = None
    mark_setup_dirty: Any = None

    # Exportado por la pestaña Plataforma.
    platform_status: Any = None
    refresh_platform_cards: Any = None
    refresh_needed_table: Any = None

    # Exportado por Setup.
    source: Any = None
    outdir: Any = None
    arcade_mode: Any = None
    dat: Any = None
    dat_status: Any = None
    dat_source: Any = None
    ra_cache_status: Any = None
    refresh_setup_platform_summary: Any = None

    # Exportado por Biblioteca DAT.
    online_table: Any = None
    dat_table: Any = None
    dat_manager_status: Any = None
    refresh_dat_table: Any = None

    # Exportado por Perfil.
    controls: Any = None

    # Exportado por Escaneo.
    scan_status: Any = None

    # Exportado por Resumen y Decisiones.
    refresh_coverage: Any = None
    refresh_decisions: Any = None
