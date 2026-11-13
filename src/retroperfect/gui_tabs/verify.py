"""Pestaña Verificar: auditoría de la colección contra el DAT sin tocar archivos."""
from __future__ import annotations

import asyncio

from nicegui import ui

from ..gui_context import UiContext
from ..gui_rows import _panel_class
from ..gui_state import _log_activity, guarded, state
from ..gui_widgets import _data_table, _limitar_filas, _open_path
from ..i18n import _
from ..paths import project_state_dir
from ..renaming import apply_renames, plan_renames
from ..verify import VERIFY_METRIC_LABELS, VerifyReport, report_verify, verify_collection


def status_filters() -> dict[str, str]:
    """Función y no diccionario: ver `gui_rows.styles.action_labels`."""
    return {
        "all": _("Todas las incidencias"),
        "FALTA": _("Faltantes (en DAT, no en romset)"),
        "SIN DAT": _("Fuera del DAT"),
        "MAL NOMBRADO": _("Mal nombrados"),
        "DUPLICADO": _("Duplicados"),
    }


def build(ctx: UiContext) -> None:
    with ui.tab_panel(ctx.verify_tab).classes("p-0"), ui.column().classes(_panel_class()):
        ui.label(_("Verificación contra el DAT")).classes("text-lg font-semibold")
        ui.label(_("Audita la colección escaneada sin tocar ningún archivo: juegos faltantes, ROMs fuera del DAT, archivos mal nombrados y duplicados por hash.")).classes("text-sm text-gray-600")
        verify_status = ui.label(_("Escanea con un DAT en la pestaña Escaneo y pulsa Verificar.")).classes("text-sm text-gray-600")
        holder: dict[str, VerifyReport | None] = {"report": None}

        with ui.grid().classes("w-full gap-3 grid-cols-2 md:grid-cols-4 xl:grid-cols-7"):
            metric_labels = {
                key: ui.label(f"{label}: -").classes("border border-gray-200 rounded-md p-3 text-center")
                for key, label in VERIFY_METRIC_LABELS
            }

        issue_filter = ui.select(status_filters(), value="all", label=_("Filtro")).props("outlined").classes("w-96")
        issues_table = _data_table(
            columns=[
                {"name": "status", "label": _("Estado"), "field": "status", "sortable": True, "align": "center"},
                {"name": "title", "label": _("Juego"), "field": "title", "sortable": True, "align": "left"},
                {"name": "detail", "label": _("Detalle"), "field": "detail", "align": "left"},
            ],
            rows=[],
            pagination=15,
        )
        issues_table.add_slot(
            "body-cell-status",
            """
                <q-td :props="props" class="rp-center">
                  <q-badge v-if="props.value === 'FALTA'" color="red" label="FALTA" />
                  <q-badge v-else-if="props.value === 'SIN DAT'" color="brown" label="SIN DAT" />
                  <q-badge v-else-if="props.value === 'MAL NOMBRADO'" color="amber" text-color="black" label="MAL NOMBRADO" />
                  <q-badge v-else color="teal" label="DUPLICADO" />
                </q-td>
                """,
        )

        def refresh_issues() -> None:
            report = holder["report"]
            if report is None:
                issues_table.rows = []
            else:
                selected = issue_filter.value
                issues_table.rows = [
                    {"status": issue.status, "title": issue.title, "detail": issue.detail}
                    for issue in report.issues
                    if selected == "all" or issue.status == selected
                ]
            issues_table.update()

        async def verify_click() -> None:
            if state.scan is None:
                verify_status.text = _("Escanea una colección antes de verificar.")
                return
            if state.catalog is None:
                verify_status.text = _("El escaneo se hizo sin DAT; selecciona un DAT en Setup y escanea de nuevo.")
                return
            verify_status.text = _("Verificando colección...")
            with guarded(verify_status, "Error al verificar", busy_label="verificación de la colección"):
                report = await asyncio.to_thread(verify_collection, state.scan, state.catalog)
                holder["report"] = report
                for key, label in VERIFY_METRIC_LABELS:
                    metric_labels[key].text = f"{label}: {getattr(report, key)}"
                refresh_issues()
                if report.clean:
                    verify_status.text = _("Colección verificada: sin incidencias respecto al DAT. ✔")
                else:
                    verify_status.text = f"Verificación completada: {len(report.issues)} incidencias (faltan {report.missing}, fuera del DAT {report.unmatched}, mal nombrados {report.misnamed}, duplicados {report.duplicates})."
                _log_activity(f"Verificación: {len(report.issues)} incidencias", "OK" if report.clean else "WARN")

        async def export_click() -> None:
            report = holder["report"]
            if report is None:
                verify_status.text = _("Verifica la colección antes de exportar el informe.")
                return
            with guarded(verify_status, "Error al exportar el informe", busy_label="exportación del informe"):
                path = await asyncio.to_thread(report_verify, report, project_state_dir() / "reports" / "verify.html", "html")
                verify_status.text = f"Informe guardado en {path}"
                _open_path(path)

        # Renombrar vive aquí porque es aquí donde se ven los mal nombrados: el
        # núcleo sabe arreglarlos y la interfaz no puede remitir a la terminal.
        ui.label(_("Arreglar los nombres")).classes("text-md font-semibold")
        ui.label(_("Renombra en el sitio los archivos que no se llaman como dice el DAT. No mueve nada, no sobrescribe nada y los que están dentro de un ZIP se omiten (harían falta reempaquetarlos).")).classes("text-sm text-gray-600")
        rename_confirm = ui.checkbox(_("He revisado la lista y autorizo renombrar"), value=False)
        rename_table = _data_table(
            columns=[
                {"name": "current", "label": _("Actual"), "field": "current", "sortable": True, "align": "left"},
                {"name": "expected", "label": _("Pasaría a llamarse"), "field": "expected", "align": "left"},
                {"name": "note", "label": _("Nota"), "field": "note", "align": "left"},
            ],
            rows=[],
            pagination=8,
        )
        planes: dict[str, list] = {"renames": []}

        def _refresh_rename_table() -> str:
            rename_table.rows, recorte = _limitar_filas(
                [
                    {
                        "current": plan.current_name,
                        "expected": plan.expected_name if plan.can_apply else "—",
                        "note": plan.skipped_reason,
                    }
                    for plan in planes["renames"]
                ]
            )
            rename_table.update()
            return recorte

        def plan_renames_click() -> None:
            if state.scan is None:
                verify_status.text = _("Escanea una colección antes de planificar renombrados.")
                return
            with guarded(verify_status, "Error al planificar los renombrados", busy_label="plan de renombrados"):
                planes["renames"] = plan_renames(state.scan)
                recorte = _refresh_rename_table()
                renombrables = sum(1 for plan in planes["renames"] if plan.can_apply)
                omitidos = len(planes["renames"]) - renombrables
                if not planes["renames"]:
                    verify_status.text = _("Todos los archivos reconocidos se llaman como dice el DAT.")
                else:
                    verify_status.text = f"Se renombrarían {renombrables} archivo(s); omitidos {omitidos}.{recorte}"

        async def apply_renames_click() -> None:
            if not planes["renames"]:
                verify_status.text = _("Planifica primero los renombrados para ver qué cambiaría.")
                return
            if not rename_confirm.value:
                verify_status.text = _("Marca la confirmación tras revisar la lista de renombrados.")
                return
            with guarded(verify_status, "Error al renombrar", busy_label="renombrado de archivos"):
                log = await asyncio.to_thread(apply_renames, planes["renames"])
                hechos = sum(1 for linea in log if linea.startswith("renombrado "))
                for linea in log:
                    if not linea.startswith("renombrado "):
                        _log_activity(linea, "WARN")
                _log_activity(f"Renombrados {hechos} archivo(s) según el DAT", "OK")
                planes["renames"] = []
                _refresh_rename_table()
                rename_confirm.value = False
                verify_status.text = f"Renombrados {hechos} archivo(s). Vuelve a escanear para que la colección refleje los nombres nuevos."

        issue_filter.on_value_change(lambda _: refresh_issues())
        with ui.row():
            ui.button(_("Verificar colección"), icon="verified", on_click=verify_click).props("color=primary")
            ui.button(_("Exportar informe HTML"), icon="article", on_click=export_click).props("outline")
            ui.button(_("Planificar renombrados"), icon="drive_file_rename_outline", on_click=plan_renames_click).props("outline")
            ui.button(_("Renombrar"), icon="edit", on_click=apply_renames_click).props("color=secondary")
