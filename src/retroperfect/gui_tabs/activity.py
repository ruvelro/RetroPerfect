"""Pestaña Actividad: registro local de acciones de la sesión y papelera."""
from __future__ import annotations

import asyncio

from nicegui import ui

from ..download_plan import human_size
from ..gui_context import UiContext
from ..gui_rows import (
    _panel_class,
)
from ..gui_state import _activity_rows, _log_activity, guarded
from ..gui_widgets import _data_table, _open_path
from ..i18n import _
from ..paths import project_state_dir
from ..trash import list_sessions, restore_session
from ..undoing import apply_undo, list_journals, plan_undo


def build(ctx: UiContext) -> None:
    with ui.tab_panel(ctx.activity_tab).classes("p-0"), ui.column().classes(_panel_class()):
        ui.label(_("Actividad")).classes("text-lg font-semibold")
        ui.label(_("Registro local de acciones importantes de esta sesión: diagnósticos, escaneos, descargas DAT, planes y RA.")).classes("text-sm text-gray-600")
        activity_table = _data_table(
            columns=[
                {"name": "time", "label": _("Hora"), "field": "time", "sortable": True, "align": "center"},
                {"name": "level", "label": _("Tipo"), "field": "level", "sortable": True, "align": "center"},
                {"name": "message", "label": _("Mensaje"), "field": "message", "align": "left"},
            ],
            rows=_activity_rows(),
            pagination=12,
        )

        def refresh_activity() -> None:
            activity_table.rows = _activity_rows()
            activity_table.update()

        with ui.row():
            ui.button(_("Refrescar"), icon="refresh", on_click=refresh_activity).props("outline")
            ui.button(_("Abrir carpeta del proyecto"), icon="folder_open", on_click=lambda: _open_path(project_state_dir())).props("outline")

        # --- Papelera ----------------------------------------------------------
        # Borrar mueve aquí en vez de destruir, así que deshacerlo tiene que poder
        # hacerse desde la app y no solo con `retroperfect trash-restore`. Va en
        # Actividad, no en Plan, porque restaurar es recuperarse de algo ya hecho:
        # exigir Setup validado y un escaneo para deshacer un borrado no tiene sentido.
        ui.separator()
        ui.label(_("Papelera")).classes("text-md font-semibold")
        ui.label(_("Lo que RetroPerfect borra se guarda aquí por sesión. Selecciona una y restáurala a sus rutas originales.")).classes("text-sm text-gray-600")
        trash_status = ui.label("").classes("text-sm text-gray-600")
        trash_table = _data_table(
            columns=[
                {"name": "name", "label": _("Sesión"), "field": "name", "sortable": True, "align": "left"},
                {"name": "created", "label": _("Creada"), "field": "created", "sortable": True, "align": "left"},
                {"name": "files", "label": _("Archivos"), "field": "files", "sortable": True, "align": "right"},
                {"name": "size", "label": _("Tamaño"), "field": "size", "align": "right"},
                {"name": "restorable", "label": _("Restaurable"), "field": "restorable", "align": "center"},
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
                trash_status.text = _("Selecciona la sesión que quieres restaurar.")
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
            ui.button(_("Refrescar papelera"), icon="refresh", on_click=refresh_trash).props("flat")
            ui.button(_("Restaurar sesión"), icon="restore_from_trash", on_click=restore_trash_click).props("color=primary")
            ui.button(_("Abrir papelera"), icon="delete_sweep", on_click=lambda: _open_path(project_state_dir() / "trash")).props("outline")

        # --- Deshacer ----------------------------------------------------------
        # Mismo razonamiento que la papelera: deshacer es recuperarse de algo ya
        # hecho, así que no puede exigir Setup validado ni escaneo, y tiene que
        # estar aquí y no solo en `retroperfect undo`.
        ui.separator()
        ui.label(_("Deshacer una aplicación")).classes("text-md font-semibold")
        ui.label(_("Cada aplicación queda registrada. Elige una y se deshace al revés: se borra lo que se copió, se devuelve lo que se movió y se saca de la papelera lo que se borró. Nada que hayas cambiado después se toca.")).classes("text-sm text-gray-600")
        undo_status = ui.label("").classes("text-sm text-gray-600")
        undo_table = _data_table(
            columns=[
                {"name": "name", "label": _("Aplicación"), "field": "name", "sortable": True, "align": "left"},
                {"name": "applied_at", "label": _("Cuándo"), "field": "applied_at", "sortable": True, "align": "left"},
                {"name": "platform", "label": _("Plataforma"), "field": "platform", "align": "center"},
                {"name": "steps", "label": _("Se deshará"), "field": "steps", "align": "right"},
                {"name": "note", "label": _("Nota"), "field": "note", "align": "left"},
            ],
            rows=[],
            row_key="name",
            selection="single",
            pagination=5,
        )

        def refresh_undo() -> None:
            filas = []
            for journal in list_journals():
                try:
                    plan = plan_undo(journal)
                except ValueError as exc:
                    filas.append({"name": journal.name, "applied_at": "", "platform": "", "steps": 0, "note": str(exc)})
                    continue
                nota = f"{plan.hard_deleted} borrado(s) definitivo(s) irrecuperables" if plan.hard_deleted else ""
                filas.append(
                    {
                        "name": journal.name,
                        "applied_at": plan.applied_at,
                        "platform": plan.platform,
                        "steps": len(plan.applicable),
                        "note": nota,
                    }
                )
            undo_table.rows = filas
            undo_table.selected = []
            undo_table.update()
            undo_status.text = "No hay ninguna aplicación registrada todavía." if not filas else f"{len(filas)} aplicación(es) registradas."

        async def undo_click() -> None:
            selected = undo_table.selected
            if not selected:
                undo_status.text = _("Selecciona la aplicación que quieres deshacer.")
                return
            nombre = selected[0]["name"]
            journal = next((item for item in list_journals() if item.name == nombre), None)
            if journal is None:
                undo_status.text = f"El registro {nombre} ya no está."
                refresh_undo()
                return
            with guarded(undo_status, "No se pudo deshacer", busy_label="deshaciendo una aplicación"):
                plan = plan_undo(journal)
                if not plan.applicable:
                    undo_status.text = f"{nombre} no tiene nada que se pueda deshacer ahora mismo."
                    return
                log = await asyncio.to_thread(apply_undo, plan)
                hechas = sum(1 for linea in log if not linea.startswith("omitido ") and not linea.startswith("error "))
                for linea in log:
                    if linea.startswith(("omitido ", "error ")):
                        _log_activity(f"Deshacer {nombre}: {linea}", "WARN")
                _log_activity(f"Aplicación deshecha: {nombre} ({hechas} operaciones)", "OK")
                undo_status.text = f"{nombre}: {hechas} operación(es) deshechas. Vuelve a escanear para que la colección refleje el estado actual."
                refresh_undo()

        with ui.row():
            ui.button(_("Refrescar aplicaciones"), icon="refresh", on_click=refresh_undo).props("flat")
            ui.button(_("Deshacer aplicación"), icon="undo", on_click=undo_click).props("color=secondary")

        refresh_trash()
        refresh_undo()

        ui.timer(1.0, refresh_activity)
