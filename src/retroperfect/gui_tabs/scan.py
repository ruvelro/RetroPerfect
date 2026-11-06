"""Pestaña Escaneo: configuración activa, diagnóstico, escaneo y resultados."""
from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path

from nicegui import ui

from ..coverage import build_coverage
from ..dat import DatIndex, parse_dat
from ..dat_manager import import_dat_file
from ..diagnostics import build_needed_rows
from ..gui_context import UiContext
from ..gui_rows import (
    _diagnostic_rows,
    _duplicate_rows,
    _flag_regions,
    _panel_class,
    _ra_icon,
    _unmatched_rows,
)
from ..gui_state import _current_platform, _log_activity, guarded, state
from ..gui_widgets import _data_table, _limitar_filas
from ..i18n import _
from ..paths import project_state_dir
from ..platforms import platform_spec
from ..ra import annotate_scan_with_ra
from ..scanner import scan_directory
from ..storage import save_scan


def build(ctx: UiContext) -> None:
    cancel_flag = {"cancelled": False}
    with ui.tab_panel(ctx.scan_tab).classes("p-0"), ui.column().classes(_panel_class()):
        ui.label(_("Configuración activa")).classes("text-lg font-semibold")
        with ui.grid(columns=4).classes("w-full gap-3"):
            active_platform = ui.label(_("Plataforma: NES / Famicom")).classes("border border-gray-200 rounded-md p-3")
            active_source = ui.label(_("Origen: sin seleccionar")).classes("border border-gray-200 rounded-md p-3")
            active_dat = ui.label(_("DAT: sin seleccionar")).classes("border border-gray-200 rounded-md p-3")
            active_out = ui.label(_("Salida: sin seleccionar")).classes("border border-gray-200 rounded-md p-3")
        def refresh_active_config() -> None:
            active_platform.text = f"Plataforma: {platform_spec(_current_platform()).short_name}"
            active_source.text = f"Origen: {ctx.source.value or 'sin seleccionar'}"
            active_dat.text = f"DAT: {ctx.dat.value or 'sin seleccionar'}"
            active_out.text = f"Salida: {ctx.outdir.value or 'sin seleccionar'}"

        scan_status = ui.label(_("Sin escaneo todavía.")).classes("text-sm text-gray-600")
        scan_progress = ui.linear_progress(value=0, show_value=False).props("instant-feedback").classes("w-full")
        scan_progress_label = ui.label(_("0% · 0 / 0 archivos · 0 ROMs · 0 matches")).classes("text-sm text-gray-600")
        scan_current_file = ui.label("").classes("text-xs text-gray-500")
        diagnostic_table = _data_table(
            card=False,
            columns=[
                {"name": "status", "label": "", "field": "status", "align": "center"},
                {"name": "item", "label": _("Chequeo"), "field": "item", "sortable": True, "align": "left"},
                {"name": "detail", "label": _("Resultado"), "field": "detail", "align": "left"},
                {"name": "recommendation", "label": _("Qué hacer"), "field": "recommendation", "align": "left"},
            ],
            rows=[],
            pagination=5,
        )
        diagnostic_table.add_slot(
            "body-cell-status",
            """
                <q-td :props="props" class="rp-center">
                  <q-badge v-if="props.value === 'OK'" color="green" label="OK" />
                  <q-badge v-else-if="props.value === 'WARN'" color="amber" text-color="black" label="WARN" />
                  <q-badge v-else-if="props.value === 'MISS'" color="red" label="MISS" />
                  <q-badge v-else color="blue-grey" label="INFO" />
                </q-td>
                """,
        )
        scan_table = _data_table(
            columns=[
                {"name": "file", "label": _("Archivo"), "field": "file", "sortable": True, "align": "left"},
                {"name": "dat", "label": _("DAT"), "field": "dat", "sortable": True, "align": "left"},
                {"name": "ra", "label": _("RA"), "field": "ra", "sortable": True, "align": "center"},
                {"name": "region", "label": _("Región"), "field": "region", "align": "center"},
                {"name": "tags", "label": _("Tags"), "field": "tags", "align": "right"},
            ],
            rows=[],
            pagination=15,
        )
        ui.label(_("No coincidencias y duplicados")).classes("text-md font-semibold")
        with ui.grid(columns=2).classes("w-full gap-3"):
            unmatched_table = _data_table(
                columns=[
                    {"name": "type", "label": _("Tipo"), "field": "type", "sortable": True, "align": "left"},
                    {"name": "file", "label": _("Archivo"), "field": "file", "sortable": True, "align": "left"},
                    {"name": "region", "label": _("Región"), "field": "region", "align": "center"},
                    {"name": "md5", "label": _("MD5"), "field": "md5", "align": "left"},
                    {"name": "suggestion", "label": _("Sugerencia"), "field": "suggestion", "align": "left"},
                ],
                rows=[],
                pagination=6,
            )
            duplicate_table = _data_table(
                columns=[
                    {"name": "kind", "label": _("Tipo"), "field": "kind", "sortable": True, "align": "left"},
                    {"name": "game", "label": _("Juego"), "field": "game", "sortable": True, "align": "left"},
                    {"name": "count", "label": _("N"), "field": "count", "sortable": True, "align": "right"},
                    {"name": "detail", "label": _("Detalle"), "field": "detail", "align": "left"},
                ],
                rows=[],
                pagination=6,
            )

        async def scan_click() -> None:
            refresh_active_config()
            if not ctx.source.value:
                scan_status.text = _("Selecciona un origen antes de escanear.")
                return
            with guarded(scan_status, "Error de escaneo", busy_label="escaneo de la colección"):
                try:
                    cancel_flag["cancelled"] = False
                    state.scan_progress = {"current": 0, "total": 0, "path": "", "roms": 0, "matched": 0, "phase": "preparing"}
                    dat_path = Path(ctx.dat.value) if ctx.dat.value else None
                    if dat_path and dat_path.suffix.lower() == ".zip":
                        imported = await asyncio.to_thread(import_dat_file, dat_path)
                        dat_path = Path(imported[0].path)
                        try:
                            state.suppress_setup_dirty = True
                            ctx.dat.value = str(dat_path)
                        finally:
                            state.suppress_setup_dirty = False
                    scan_status.text = _("Cargando e indexando DAT...")
                    catalog = await asyncio.to_thread(parse_dat, dat_path) if dat_path else None
                    dat_index = await asyncio.to_thread(DatIndex, catalog) if catalog else None
                    scan_status.text = _("Escaneando ZIPs/ROMs... en romsets grandes puede tardar unos minutos.")

                    def progress_update(update: dict[str, object]) -> None:
                        state.scan_progress = update

                    result = await asyncio.to_thread(
                        partial(
                            scan_directory,
                            Path(ctx.source.value),
                            _current_platform(),
                            dat_index,
                            dat_path,
                            progress_update,
                            project_state_dir() / "scan-cache.sqlite3",
                            cancelled=lambda: cancel_flag["cancelled"],
                        )
                    )
                    if cancel_flag["cancelled"]:
                        # Se guarda lo escaneado igual: sirve para seguir, pero
                        # no se puede presentar como la colección completa.
                        save_scan(result)
                        state.scan = result
                        state.catalog = catalog
                        state.coverage = build_coverage(result, catalog)
                        ctx.update_tab_access()
                        scan_status.text = f"Escaneo cancelado tras {len(result.roms)} candidatos. El resultado está incompleto: vuelve a escanear para curar."
                        _log_activity(f"Escaneo cancelado por el usuario tras {len(result.roms)} ROMs", "WARN")
                        return
                    result = await asyncio.to_thread(annotate_scan_with_ra, result)
                    save_scan(result)
                    state.scan = result
                    state.catalog = catalog
                    state.coverage = build_coverage(result, catalog)
                    ctx.update_tab_access()
                    scan_table.rows, recorte = _limitar_filas(
                        [
                            {
                                "file": Path(rom.container_path).name if not rom.inner_path else f"{Path(rom.container_path).name} / {rom.inner_path}",
                                "dat": rom.dat_game.name if rom.dat_game else "",
                                "ra": " ".join(part for part in [_ra_icon(rom), rom.ra_title or rom.ra_hash_name or ""] if part),
                                "region": _flag_regions(rom.metadata.regions),
                                "tags": ", ".join(rom.metadata.tags),
                            }
                            for rom in result.roms
                        ]
                    )
                    scan_table.update()
                    unmatched_table.rows = _unmatched_rows(result)
                    unmatched_table.update()
                    duplicate_table.rows = _duplicate_rows(result)
                    duplicate_table.update()
                    ra_matches = sum(1 for rom in result.roms if rom.ra_game_id)
                    scan_status.text = f"Escaneados {len(result.roms)} candidatos. Coincidencias RA: {ra_matches}. No reconocidos: {len(result.unmatched_files)}.{recorte}"
                    _log_activity(f"Escaneo completado: {len(result.roms)} ROMs, {ra_matches} RA, {len(result.unmatched_files)} no reconocidos", "OK")
                    ctx.refresh_needed_table()
                    ctx.refresh_coverage()
                    ctx.refresh_decisions()
                finally:
                    # Si el escaneo falla a medias, la fase se quedaba en "preparing"
                    # y el guard de cierre creía que seguía escaneando para siempre.
                    if state.scan_progress.get("phase") in {"preparing", "start", "scan"}:
                        state.scan_progress = {**state.scan_progress, "phase": "idle"}

        with ui.row():
            ui.button(_("Actualizar configuración"), icon="refresh", on_click=refresh_active_config).props("outline")
            def diagnostic_click() -> None:
                refresh_active_config()
                diagnostic_table.rows = _diagnostic_rows(
                    build_needed_rows(
                        _current_platform(),
                        Path(ctx.source.value) if ctx.source.value else None,
                        Path(ctx.dat.value) if ctx.dat.value else None,
                        state.scan,
                    )
                )
                diagnostic_table.update()
                scan_status.text = _("Diagnóstico actualizado. Si ves WARN/MISS, corrige eso antes de escanear.")
                _log_activity("Diagnóstico rápido actualizado", "INFO")

            ui.button(_("Diagnóstico rápido"), icon="troubleshoot", on_click=diagnostic_click).props("outline")
            ui.button(_("Escanear colección"), icon="search", on_click=scan_click).props("color=primary")

            def cancel_scan_click() -> None:
                cancel_flag["cancelled"] = True
                scan_status.text = _("Cancelando tras el archivo en curso...")

            ui.button(_("Cancelar escaneo"), icon="stop_circle", on_click=cancel_scan_click).props("outline")

        def refresh_scan_progress() -> None:
            progress = state.scan_progress
            current = int(progress.get("current", 0) or 0)
            total = int(progress.get("total", 0) or 0)
            roms = int(progress.get("roms", 0) or 0)
            matched = int(progress.get("matched", 0) or 0)
            value = current / total if total else 0
            scan_progress.value = value
            percent = round(value * 100)
            scan_progress_label.text = f"{percent}% · {current} / {total} archivos · {roms} ROMs · {matched} matches"
            current_path = str(progress.get("path", "") or "")
            scan_current_file.text = f"Procesando: {Path(current_path).name}" if current_path else ""

        ui.timer(0.3, refresh_scan_progress)

    ctx.scan_status = scan_status
