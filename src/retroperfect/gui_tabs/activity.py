"""Pestaña Actividad: registro local de acciones de la sesión y papelera."""
from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui

from ..download_plan import human_size
from ..gui_context import UiContext
from ..gui_rows import (
    _panel_class,
)
from ..gui_state import _activity_rows, _log_activity, guarded
from ..gui_widgets import _data_table, _open_path
from ..paths import project_state_dir
from ..trash import list_sessions, restore_session


def build(ctx: UiContext) -> None:
    with ui.tab_panel(ctx.activity_tab).classes("p-0"), ui.column().classes(_panel_class()):
        ui.label("Actividad").classes("text-lg font-semibold")
        ui.label("Registro local de acciones importantes de esta sesión: diagnósticos, escaneos, descargas DAT, planes y RA.").classes("text-sm text-gray-600")
        activity_table = _data_table(
            columns=[
                {"name": "time", "label": "Hora", "field": "time", "sortable": True, "align": "center"},
                {"name": "level", "label": "Tipo", "field": "level", "sortable": True, "align": "center"},
                {"name": "message", "label": "Mensaje", "field": "message", "align": "left"},
            ],
            rows=_activity_rows(),
            pagination=12,
        )

        def refresh_activity() -> None:
            activity_table.rows = _activity_rows()
            activity_table.update()

        with ui.row():
            ui.button("Refrescar", icon="refresh", on_click=refresh_activity).props("outline")
            ui.button("Abrir carpeta del proyecto", icon="folder_open", on_click=lambda: _open_path(project_state_dir())).props("outline")

        # --- Papelera ----------------------------------------------------------
        # Borrar mueve aquí en vez de destruir, así que deshacerlo tiene que poder
        # hacerse desde la app y no solo con `retroperfect trash-restore`. Va en
        # Actividad, no en Plan, porque restaurar es recuperarse de algo ya hecho:
        # exigir Setup validado y un escaneo para deshacer un borrado no tiene sentido.
        ui.separator()
        ui.label("Papelera").classes("text-md font-semibold")
        ui.label("Lo que RetroPerfect borra se guarda aquí por sesión. Selecciona una y restáurala a sus rutas originales.").classes("text-sm text-gray-600")
        trash_status = ui.label("").classes("text-sm text-gray-600")
        trash_table = _data_table(
            columns=[
                {"name": "name", "label": "Sesión", "field": "name", "sortable": True, "align": "left"},
                {"name": "created", "label": "Creada", "field": "created", "sortable": True, "align": "left"},
                {"name": "files", "label": "Archivos", "field": "files", "sortable": True, "align": "right"},
                {"name": "size", "label": "Tamaño", "field": "size", "align": "right"},
                {"name": "restorable", "label": "Restaurable", "field": "restorable", "align": "center"},
            ],
            rows=[],
            row_key="name",
            selection="single",
            pagination=5,
        )

        def refresh_trash() -> None:
            sessions = list_sessions()
            trash_table.rows = [
                {
                    "name": session.name,
                    "created": session.created,
                    "files": session.files,
                    "size": human_size(session.total_size),
                    "restorable": "sí" if session.restorable else "no",
                }
                for session in sessions
            ]
            trash_table.selected = []
            trash_table.update()
            trash_status.text = "La papelera está vacía." if not sessions else f"{len(sessions)} sesión(es) en la papelera."

        async def restore_trash_click() -> None:
            selected = trash_table.selected
            if not selected:
                trash_status.text = "Selecciona la sesión que quieres restaurar."
                return
            name = selected[0]["name"]
            with guarded(trash_status, "No se pudo restaurar", busy_label="restauración de la papelera"):
                lines = await asyncio.to_thread(restore_session, name)
                # restore_session devuelve un log, no una lista de archivos: incluye
                # los omitidos y el aviso de que la sesión se ha eliminado.
                restored = sum(1 for line in lines if line.startswith("restaurado "))
                skipped = [line for line in lines if line.startswith("omitido ")]
                trash_status.text = f"Sesión {name}: {restored} archivo(s) devueltos a su ruta original." + (f" {len(skipped)} omitido(s)." if skipped else "")
                for line in skipped:
                    _log_activity(f"Papelera {name}: {line}", "WARN")
                _log_activity(f"Papelera restaurada: {name} ({restored} archivos)", "OK")
                refresh_trash()

        with ui.row():
            ui.button("Refrescar papelera", icon="refresh", on_click=refresh_trash).props("flat")
            ui.button("Restaurar sesión", icon="restore_from_trash", on_click=restore_trash_click).props("color=primary")
            ui.button("Abrir papelera", icon="delete_sweep", on_click=lambda: _open_path(Path(".retroperfect/trash"))).props("outline")

        refresh_trash()

        ui.timer(1.0, refresh_activity)
