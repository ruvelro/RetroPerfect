"""Pestaña Verificar: auditoría de la colección contra el DAT sin tocar archivos."""
from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui

from ..gui_context import UiContext
from ..gui_rows import _panel_class
from ..gui_state import _log_activity, state
from ..gui_widgets import _open_path
from ..verify import VERIFY_METRIC_LABELS, VerifyReport, report_verify, verify_collection

STATUS_FILTERS = {
    "all": "Todas las incidencias",
    "FALTA": "Faltantes (en DAT, no en romset)",
    "SIN DAT": "Fuera del DAT",
    "MAL NOMBRADO": "Mal nombrados",
    "DUPLICADO": "Duplicados",
}


def build(ctx: UiContext) -> None:
    with ui.tab_panel(ctx.verify_tab).classes("p-0"), ui.column().classes(_panel_class()):
        ui.label("Verificación contra el DAT").classes("text-lg font-semibold")
        ui.label("Audita la colección escaneada sin tocar ningún archivo: juegos faltantes, ROMs fuera del DAT, archivos mal nombrados y duplicados por hash.").classes("text-sm text-gray-600")
        verify_status = ui.label("Escanea con un DAT en la pestaña Escaneo y pulsa Verificar.").classes("text-sm text-gray-600")
        holder: dict[str, VerifyReport | None] = {"report": None}

        with ui.grid().classes("w-full gap-3 grid-cols-2 md:grid-cols-4 xl:grid-cols-7"):
            metric_labels = {
                key: ui.label(f"{label}: -").classes("border border-gray-200 rounded-md p-3 text-center")
                for key, label in VERIFY_METRIC_LABELS
            }

        issue_filter = ui.select(STATUS_FILTERS, value="all", label="Filtro").props("outlined").classes("w-96")
        issues_table = ui.table(
            columns=[
                {"name": "status", "label": "Estado", "field": "status", "sortable": True, "align": "center"},
                {"name": "title", "label": "Juego", "field": "title", "sortable": True, "align": "left"},
                {"name": "detail", "label": "Detalle", "field": "detail", "align": "left"},
            ],
            rows=[],
            pagination=15,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")
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
                verify_status.text = "Escanea una colección antes de verificar."
                return
            if state.catalog is None:
                verify_status.text = "El escaneo se hizo sin DAT; selecciona un DAT en Setup y escanea de nuevo."
                return
            verify_status.text = "Verificando colección..."
            report = await asyncio.to_thread(verify_collection, state.scan, state.catalog)
            holder["report"] = report
            for key, label in VERIFY_METRIC_LABELS:
                metric_labels[key].text = f"{label}: {getattr(report, key)}"
            refresh_issues()
            if report.clean:
                verify_status.text = "Colección verificada: sin incidencias respecto al DAT. ✔"
            else:
                verify_status.text = f"Verificación completada: {len(report.issues)} incidencias (faltan {report.missing}, fuera del DAT {report.unmatched}, mal nombrados {report.misnamed}, duplicados {report.duplicates})."
            _log_activity(f"Verificación: {len(report.issues)} incidencias", "OK" if report.clean else "WARN")

        async def export_click() -> None:
            report = holder["report"]
            if report is None:
                verify_status.text = "Verifica la colección antes de exportar el informe."
                return
            path = await asyncio.to_thread(report_verify, report, Path(".retroperfect/reports/verify.html"), "html")
            verify_status.text = f"Informe guardado en {path}"
            _open_path(path)

        issue_filter.on_value_change(lambda _: refresh_issues())
        with ui.row():
            ui.button("Verificar colección", icon="verified", on_click=verify_click).props("color=primary")
            ui.button("Exportar informe HTML", icon="article", on_click=export_click).props("outline")
