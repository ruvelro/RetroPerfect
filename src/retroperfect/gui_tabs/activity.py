"""Pestaña Actividad: registro local de acciones de la sesión."""
from __future__ import annotations

from nicegui import ui

from ..gui_context import UiContext
from ..gui_rows import (
    _panel_class,
)
from ..gui_state import _activity_rows
from ..gui_widgets import _open_path
from ..paths import project_state_dir


def build(ctx: UiContext) -> None:
    with ui.tab_panel(ctx.activity_tab).classes("p-0"), ui.column().classes(_panel_class()):
        ui.label("Actividad").classes("text-lg font-semibold")
        ui.label("Registro local de acciones importantes de esta sesión: diagnósticos, escaneos, descargas DAT, planes y RA.").classes("text-sm text-gray-600")
        activity_table = ui.table(
            columns=[
                {"name": "time", "label": "Hora", "field": "time", "sortable": True, "align": "center"},
                {"name": "level", "label": "Tipo", "field": "level", "sortable": True, "align": "center"},
                {"name": "message", "label": "Mensaje", "field": "message", "align": "left"},
            ],
            rows=_activity_rows(),
            pagination=12,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")

        def refresh_activity() -> None:
            activity_table.rows = _activity_rows()
            activity_table.update()

        with ui.row():
            ui.button("Refrescar", icon="refresh", on_click=refresh_activity).props("outline")
            ui.button("Abrir carpeta del proyecto", icon="folder_open", on_click=lambda: _open_path(project_state_dir())).props("outline")

        ui.timer(1.0, refresh_activity)
