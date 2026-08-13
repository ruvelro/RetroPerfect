"""Pestaña Biblioteca DAT: fuentes online, lote, importación local y comparador."""
from __future__ import annotations

import asyncio
import webbrowser
from pathlib import Path

from nicegui import ui

from ..dat_manager import compare_dats, download_and_import_source, download_and_import_url, import_dat_file, stale_dats, update_installed_dats
from ..dat_sources import DAT_SOURCES
from ..gui_context import UiContext
from ..gui_rows import (
    DATOMATIC_GAP_ROWS,
    _dat_rows,
    _direct_dat_batch_candidates,
    _panel_class,
)
from ..gui_state import _current_platform, _log_activity, _online_dat_rows
from ..gui_widgets import _path_picker
from ..platforms import platform_spec


def build(ctx: UiContext) -> None:
    with ui.tab_panel(ctx.dats_tab).classes("p-0"), ui.column().classes(_panel_class()):
        ui.label("Biblioteca de DATs").classes("text-lg font-semibold")
        dat_manager_status = ui.label("Aqui se descargan/importan DATs, se registran con metadatos y se elige cual usar para el escaneo actual.").classes("text-sm text-gray-600")
        ui.label("Fuentes online").classes("text-md font-semibold")
        online_table = ui.table(
            columns=[
                {"name": "label", "label": "Fuente", "field": "label", "sortable": True, "align": "left"},
                {"name": "format", "label": "Formato", "field": "format", "align": "left"},
                {"name": "direct", "label": "Descarga directa", "field": "direct", "sortable": True},
                {"name": "notes", "label": "Notas", "field": "notes", "align": "left"},
            ],
            rows=_online_dat_rows(_current_platform()),
            row_key="id",
            selection="single",
            pagination=6,
        ).classes("w-full rp-table-card")

        async def download_online_click() -> None:
            selected = online_table.selected
            if not selected:
                dat_manager_status.text = "Selecciona una fuente online."
                return
            try:
                imported = await asyncio.to_thread(download_and_import_source, selected[0]["id"])
                ctx.dat.value = imported[0].path
                dat_manager_status.text = f"Descargados/importados {len(imported)} DATs. Activo: {imported[0].name}"
                refresh_dat_table()
            except Exception as exc:
                dat_manager_status.text = f"No se pudo descargar automáticamente: {exc}"

        def open_online_click() -> None:
            selected = online_table.selected
            if not selected:
                dat_manager_status.text = "Selecciona una fuente online."
                return
            webbrowser.open(selected[0]["url"])
            dat_manager_status.text = "Fuente abierta en el navegador. Si descarga un ZIP, impórtalo aquí."

        custom_url = ui.input("URL directa a DAT/XML/ZIP").props("outlined").classes("w-full")
        custom_filename = ui.input("Nombre de archivo opcional").props("outlined").classes("w-96")

        async def download_url_click() -> None:
            if not custom_url.value:
                dat_manager_status.text = "Introduce una URL directa."
                return
            try:
                imported = await asyncio.to_thread(download_and_import_url, custom_url.value, custom_filename.value or None)
                ctx.dat.value = imported[0].path
                dat_manager_status.text = f"URL descargada/importada: {imported[0].name}"
                refresh_dat_table()
            except Exception as exc:
                dat_manager_status.text = f"No se pudo descargar la URL: {exc}"

        with ui.row():
            ui.button("Descargar fuente", icon="download", on_click=download_online_click).props("color=primary")
            ui.button("Abrir fuente", icon="open_in_browser", on_click=open_online_click).props("outline")
            ui.button("Descargar URL", icon="link", on_click=download_url_click).props("outline")

        ui.separator()
        ui.label("Mantenimiento").classes("text-md font-semibold")
        stale = stale_dats()
        stale_label = ui.label(
            f"{len(stale)} DAT(s) de fuentes directas llevan más de 7 días sin actualizar." if stale else "Los DATs de fuentes directas están al día (menos de 7 días)."
        ).classes("text-sm " + ("text-amber-700" if stale else "text-gray-600"))

        async def update_dats_click() -> None:
            dat_manager_status.text = "Re-descargando DATs instalados de fuentes directas..."
            results = await asyncio.to_thread(update_installed_dats)
            if not results:
                dat_manager_status.text = "No hay DATs de fuentes directas que actualizar."
                return
            updated = sum(1 for result in results if result.status == "actualizado")
            errors = sum(1 for result in results if result.status == "error")
            changed = "; ".join(f"{result.name}: {result.detail}" for result in results if result.status == "actualizado")
            dat_manager_status.text = (
                f"Actualización terminada: {updated} con cambios, {len(results) - updated - errors} sin cambios, {errors} errores."
                + (f" Cambios: {changed}" if changed else "")
            )
            _log_activity(f"DATs actualizados: {updated} con cambios de {len(results)}", "OK" if not errors else "WARN")
            remaining = stale_dats()
            stale_label.text = (
                f"{len(remaining)} DAT(s) de fuentes directas llevan más de 7 días sin actualizar." if remaining else "Los DATs de fuentes directas están al día (menos de 7 días)."
            )
            refresh_dat_table()
            ctx.refresh_needed_table()

        ui.button("Actualizar DATs instalados", icon="update", on_click=update_dats_click).props("outline")
        ui.label("Para automatizarlo, programa 'retroperfect dat-update' con cron o el Programador de tareas.").classes("text-xs text-gray-500")

        ui.separator()
        ui.label("Descarga por lote").classes("text-md font-semibold")
        ui.label("Automático usa fuentes directas públicas. DAT-o-MATIC queda como fuente oficial asistida cuando requiere navegador o sesión.").classes("text-sm text-gray-600")
        with ui.row().classes("items-end gap-3"):
            batch_scope = ui.select(
                {"current": "Solo plataforma actual", "all": "Todas con fuente directa"},
                value="current",
                label="Alcance",
            ).props("outlined").classes("w-64")
            batch_limit = ui.number("Límite", value=20, min=1, max=300, step=10).props("outlined").classes("w-32")
            batch_progress = ui.linear_progress(value=0, show_value=False).props("instant-feedback").classes("w-64")
        batch_table = ui.table(
            columns=[
                {"name": "platform", "label": "Plataforma", "field": "platform", "sortable": True, "align": "left"},
                {"name": "source", "label": "Fuente", "field": "source", "align": "left"},
                {"name": "status", "label": "Estado", "field": "status", "sortable": True, "align": "center"},
            ],
            rows=[],
            pagination=6,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table")

        async def batch_download_click() -> None:
            source_ids = _direct_dat_batch_candidates(batch_scope.value, _current_platform(), int(batch_limit.value or 20))
            if not source_ids:
                dat_manager_status.text = "No hay fuentes directas para este alcance."
                return
            rows = []
            for source_id in source_ids:
                source_item = next(item for item in DAT_SOURCES if item.id == source_id)
                rows.append({"platform": platform_spec(source_item.platform).short_name, "source": source_item.label, "status": "pendiente"})
            batch_table.rows = rows
            batch_table.update()
            imported_total = 0
            for index, source_id in enumerate(source_ids, start=1):
                source_item = next(item for item in DAT_SOURCES if item.id == source_id)
                batch_progress.value = (index - 1) / len(source_ids)
                try:
                    imported = await asyncio.to_thread(download_and_import_source, source_id)
                    imported_total += len(imported)
                    rows[index - 1]["status"] = f"OK ({len(imported)})"
                    dat_manager_status.text = f"Descargado {index}/{len(source_ids)}: {source_item.label}"
                except Exception as exc:
                    rows[index - 1]["status"] = f"Error: {exc}"
                batch_table.rows = rows
                batch_table.update()
            batch_progress.value = 1
            dat_manager_status.text = f"Lote terminado: {imported_total} DATs importados de {len(source_ids)} fuentes."
            _log_activity(f"Lote DAT terminado: {imported_total} DATs importados", "OK")
            refresh_dat_table()
            ctx.refresh_needed_table()

        ui.button("Descargar lote directo", icon="cloud_download", on_click=batch_download_click).props("outline")

        ui.separator()
        ui.label("DAT-o-MATIC: cobertura pendiente en RetroPerfect").classes("text-md font-semibold")
        ui.label("La lista se basa en la tabla pública de sistemas de No-Intro; DAT-o-MATIC puede variar y algunos sistemas privados requieren sesión.").classes("text-sm text-gray-600")
        ui.table(
            columns=[
                {"name": "group", "label": "Grupo", "field": "group", "sortable": True, "align": "left"},
                {"name": "platform", "label": "Plataformas/variantes", "field": "platform", "align": "left"},
                {"name": "status", "label": "Estado", "field": "status", "sortable": True, "align": "center"},
            ],
            rows=DATOMATIC_GAP_ROWS,
            pagination=8,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table")

        ui.separator()
        ui.label("Importación local").classes("text-md font-semibold")
        import_path = ui.input("Archivo DAT/XML/ZIP a importar").props("outlined readonly").classes("w-full")
        import_dialog = _path_picker(import_path, choose="file", suffixes={".dat", ".xml", ".zip"})
        with ui.row():
            ui.button("Buscar DAT/ZIP", icon="upload_file", on_click=import_dialog.open).props("outline")

            async def import_click() -> None:
                if not import_path.value:
                    dat_manager_status.text = "Selecciona un DAT, XML o ZIP."
                    return
                try:
                    imported = await asyncio.to_thread(import_dat_file, Path(import_path.value))
                    ctx.dat.value = imported[0].path
                    dat_manager_status.text = f"Importados {len(imported)} DATs. Usando: {imported[0].name}"
                    refresh_dat_table()
                except Exception as exc:
                    dat_manager_status.text = f"No se pudo importar: {exc}"

            ui.button("Importar", icon="archive", on_click=import_click).props("color=primary")
        dat_table = ui.table(
            columns=[
                {"name": "name", "label": "Nombre", "field": "name", "sortable": True, "align": "left"},
                {"name": "platform", "label": "Plataforma", "field": "platform", "sortable": True, "align": "left"},
                {"name": "source", "label": "Fuente", "field": "source", "sortable": True, "align": "left"},
                {"name": "format", "label": "Formato", "field": "format", "sortable": True, "align": "left"},
                {"name": "games", "label": "Juegos", "field": "games", "sortable": True, "align": "right"},
                {"name": "roms", "label": "ROMs", "field": "roms", "sortable": True, "align": "right"},
                {"name": "pc", "label": "P/C", "field": "pc", "sortable": True, "align": "center"},
                {"name": "header", "label": "Header", "field": "header", "sortable": True, "align": "center"},
                {"name": "recommended", "label": "Recomendado", "field": "recommended", "sortable": True, "align": "center"},
                {"name": "regions", "label": "Regiones", "field": "regions", "align": "left"},
                {"name": "notes", "label": "Notas", "field": "notes", "align": "left"},
            ],
            rows=[],
            row_key="id",
            selection="multiple",
            pagination=12,
        ).classes("w-full rp-table-card")
        compare_status = ui.label().classes("text-sm text-gray-600")

        def refresh_dat_table() -> None:
            dat_table.rows = _dat_rows(_current_platform())
            dat_table.update()

        def use_selected_dat() -> None:
            selected = dat_table.selected
            if not selected:
                dat_manager_status.text = "Selecciona un DAT instalado."
                return
            ctx.dat.value = selected[0]["path"]
            dat_manager_status.text = f"DAT activo: {selected[0]['name']}"

        def compare_selected_dats() -> None:
            selected = dat_table.selected
            if len(selected) != 2:
                compare_status.text = "Selecciona exactamente dos DATs para comparar."
                return
            try:
                comparison = compare_dats(Path(selected[0]["path"]), Path(selected[1]["path"]))
                compare_status.text = (
                    f"{comparison.left_name} vs {comparison.right_name}: "
                    f"comunes {comparison.common_games} juegos / {comparison.common_roms} ROMs; "
                    f"solo primero {comparison.left_only_games} juegos / {comparison.left_only_roms} ROMs; "
                    f"solo segundo {comparison.right_only_games} juegos / {comparison.right_only_roms} ROMs."
                )
            except Exception as exc:
                compare_status.text = f"No se pudo comparar: {exc}"

        with ui.row():
            ui.button("Usar seleccionado", icon="check", on_click=use_selected_dat).props("color=primary")
            ui.button("Comparar dos DATs", icon="compare_arrows", on_click=compare_selected_dats).props("outline")
            ui.button("Refrescar", icon="refresh", on_click=refresh_dat_table).props("flat")
        refresh_dat_table()

    ctx.online_table = online_table
    ctx.dat_table = dat_table
    ctx.dat_manager_status = dat_manager_status
    ctx.refresh_dat_table = refresh_dat_table
