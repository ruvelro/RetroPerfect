"""Pestaña Descargar: fuentes propias, plan de lo que falta y descarga verificada."""
from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui

from ..dat import DatIndex
from ..download_plan import DownloadPlan, build_download_plan, human_size, resolve_remote_files
from ..downloader import run_download_plan
from ..gui_context import UiContext
from ..gui_rows import _panel_class
from ..gui_state import _current_platform, _log_activity, busy, state
from ..rom_sources import SOURCE_KIND_LABELS, RomSource, add_rom_source, list_rom_sources, remove_rom_source


def build(ctx: UiContext) -> None:
    with ui.tab_panel(ctx.download_tab).classes("p-0"), ui.column().classes(_panel_class()):
        ui.label("Descargar lo que falta").classes("text-lg font-semibold")
        ui.label(
            "RetroPerfect no incluye ningún catálogo de ROMs: las fuentes las añades tú y respondes de su contenido. "
            "La app cruza tus fuentes con el DAT y tu perfil, descarga solo lo que falta y verifica cada archivo por hash antes de instalarlo."
        ).classes("text-sm text-gray-600")

        holder: dict[str, DownloadPlan | None] = {"plan": None}
        cancel_flag = {"cancelled": False}

        # --- Fuentes configuradas ---------------------------------------------
        ui.label("Fuentes").classes("text-md font-semibold")
        sources_table = ui.table(
            columns=[
                {"name": "label", "label": "Fuente", "field": "label", "sortable": True, "align": "left"},
                {"name": "kind", "label": "Tipo", "field": "kind", "align": "left"},
                {"name": "location", "label": "Origen", "field": "location", "align": "left"},
                {"name": "platform", "label": "Plataforma", "field": "platform", "align": "center"},
            ],
            rows=[],
            row_key="id",
            selection="single",
            pagination=5,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")

        with ui.row().classes("w-full items-end gap-2"):
            source_label = ui.input("Nombre").props("outlined dense").classes("w-56")
            source_kind = ui.select(SOURCE_KIND_LABELS, value="archive_org", label="Tipo").props("outlined dense").classes("w-96")
            source_location = ui.input("Ítem, URL o carpeta").props("outlined dense").classes("grow")
            only_this_platform = ui.checkbox("Solo esta plataforma", value=True)

        status = ui.label("Añade al menos una fuente para poder calcular qué falta.").classes("text-sm text-gray-600")

        def refresh_sources() -> None:
            sources_table.rows = [
                {"id": source.id, "label": source.label, "kind": source.kind, "location": source.location, "platform": source.platform or "todas"}
                for source in list_rom_sources()
            ]
            sources_table.update()

        def add_source_click() -> None:
            if not source_label.value or not source_location.value:
                status.text = "Indica un nombre y el origen (ítem de archive.org, URL del índice o carpeta)."
                return
            platform = _current_platform().value if only_this_platform.value else None
            source_id = _source_id(source_label.value, platform)
            add_rom_source(
                RomSource(
                    id=source_id,
                    label=source_label.value,
                    kind=source_kind.value,
                    location=source_location.value.strip(),
                    platform=platform,
                )
            )
            source_label.value = ""
            source_location.value = ""
            refresh_sources()
            status.text = f"Fuente añadida. Ahora hay {len(list_rom_sources())} configuradas."
            _log_activity(f"Fuente de descarga añadida: {source_id}", "OK")

        def remove_source_click() -> None:
            selected = sources_table.selected
            if not selected:
                status.text = "Selecciona la fuente que quieres eliminar."
                return
            remove_rom_source(selected[0]["id"])
            sources_table.selected = []
            refresh_sources()
            status.text = "Fuente eliminada."

        with ui.row():
            ui.button("Añadir fuente", icon="add_link", on_click=add_source_click).props("color=primary")
            ui.button("Eliminar fuente", icon="link_off", on_click=remove_source_click).props("outline")

        # --- Plan --------------------------------------------------------------
        ui.separator()
        with ui.row().classes("items-center gap-4"):
            apply_profile = ui.checkbox("Filtrar por mi perfil (1G1R)", value=True)
            refresh_index = ui.checkbox("Releer índices remotos", value=False)

        with ui.grid().classes("w-full gap-3 grid-cols-2 md:grid-cols-4"):
            metric_labels = {
                key: ui.label(f"{label}: -").classes("border border-gray-200 rounded-md p-3 text-center")
                for key, label in [
                    ("candidates", "A descargar"),
                    ("size", "Tamaño"),
                    ("present", "Ya presentes"),
                    ("unavailable", "Sin fuente"),
                ]
            }

        plan_table = ui.table(
            columns=[
                {"name": "confidence", "label": "Coincidencia", "field": "confidence", "sortable": True, "align": "center"},
                {"name": "title", "label": "Juego", "field": "title", "sortable": True, "align": "left"},
                {"name": "file", "label": "Archivo remoto", "field": "file", "align": "left"},
                {"name": "size", "label": "Tamaño", "field": "size", "sortable": True, "align": "right"},
            ],
            rows=[],
            pagination=15,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")
        plan_table.add_slot(
            "body-cell-confidence",
            """
                <q-td :props="props" class="rp-center">
                  <q-badge v-if="props.value === 'hash'" color="green" label="HASH" />
                  <q-badge v-else-if="props.value === 'name-exact'" color="blue" label="NOMBRE" />
                  <q-badge v-else color="amber" text-color="black" label="APROX." />
                </q-td>
                """,
        )
        progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full").props("instant-feedback")
        progress_label = ui.label("").classes("text-sm text-gray-600")
        progress.visible = False

        def refresh_plan_table() -> None:
            plan = holder["plan"]
            plan_table.rows = (
                []
                if plan is None
                else [
                    {"confidence": candidate.confidence, "title": candidate.title, "file": candidate.file_name, "size": human_size(candidate.size)}
                    for candidate in plan.candidates
                ]
            )
            plan_table.update()

        async def plan_click() -> None:
            if state.catalog is None:
                status.text = "Necesitas un DAT cargado: elígelo en Setup y escanea la colección."
                return
            sources = list_rom_sources(_current_platform().value)
            if not sources:
                status.text = "No hay fuentes configuradas para esta plataforma."
                return
            status.text = "Leyendo índices de las fuentes..."
            with busy("plan de descarga"):
                remote_files, errors = await asyncio.to_thread(resolve_remote_files, sources, refresh_index.value)
                if errors:
                    status.text = "Fuentes no disponibles: " + " · ".join(errors)
                if not remote_files:
                    return
                plan = await asyncio.to_thread(
                    build_download_plan,
                    state.catalog,
                    state.scan,
                    state.profile,
                    remote_files,
                    platform=_current_platform(),
                    apply_profile=apply_profile.value,
                )
            holder["plan"] = plan
            metric_labels["candidates"].text = f"A descargar: {len(plan.candidates)}"
            metric_labels["size"].text = f"Tamaño: {human_size(plan.total_bytes)}"
            metric_labels["present"].text = f"Ya presentes: {plan.present_groups}/{plan.dat_groups}"
            metric_labels["unavailable"].text = f"Sin fuente: {len(plan.unavailable)}"
            refresh_plan_table()
            status.text = (
                f"Plan listo: {len(plan.candidates)} archivos ({human_size(plan.total_bytes)}). "
                f"{plan.filtered_by_profile} grupos descartados por el perfil, {len(plan.unavailable)} sin fuente."
            )
            _log_activity(f"Plan de descarga: {len(plan.candidates)} archivos", "OK")

        def refresh_download_progress() -> None:
            current_progress = state.download_progress
            total = int(current_progress.get("total", 0) or 0)
            current = int(current_progress.get("current", 0) or 0)
            if not total or current_progress.get("phase") == "idle":
                return
            progress.value = current / total
            progress_label.text = f"{current} / {total} · {current_progress.get('title', '')}"

        async def download_click() -> None:
            plan = holder["plan"]
            if plan is None or not plan.candidates:
                status.text = "Calcula primero un plan con candidatos."
                return
            destination = ctx.source.value
            if not destination:
                status.text = "Falta la carpeta del romset en Setup: es donde se instalará lo verificado."
                return
            cancel_flag["cancelled"] = False
            progress.visible = True

            # El hilo de descarga solo escribe en el estado; los widgets los refresca
            # este handler mientras espera, para no tocar la UI desde otro hilo.
            def on_progress(event: dict[str, object]) -> None:
                state.download_progress = {**event, "total": len(plan.candidates)}

            state.download_progress = {"current": 0, "total": len(plan.candidates), "title": "", "phase": "start"}
            with busy("descarga de romset"):
                task = asyncio.create_task(
                    asyncio.to_thread(
                        run_download_plan,
                        plan,
                        Path(destination),
                        dat_index=DatIndex(state.catalog) if state.catalog else None,
                        progress=on_progress,
                        cancelled=lambda: cancel_flag["cancelled"],
                    )
                )
                while not task.done():
                    await asyncio.sleep(0.2)
                    refresh_download_progress()
                report = await task
            progress.visible = False
            state.download_progress = {"current": 0, "total": 0, "title": "", "phase": "idle"}
            problems = [outcome for outcome in report.outcomes if outcome.status in {"mismatch", "error"}]
            status.text = (
                f"Descarga terminada: {report.downloaded} instalados ({human_size(report.total_bytes)}), "
                f"{len(problems)} con problemas. Vuelve a escanear para incorporarlos al romset."
            )
            for outcome in problems:
                _log_activity(f"{outcome.status_label}: {outcome.file_name}. {outcome.detail}", "WARN")
            _log_activity(f"Descarga: {report.downloaded} archivos verificados e instalados", "OK" if not problems else "WARN")

        def cancel_click() -> None:
            cancel_flag["cancelled"] = True
            status.text = "Cancelando tras el archivo en curso..."

        with ui.row():
            ui.button("Calcular plan", icon="playlist_add_check", on_click=plan_click).props("color=primary")
            ui.button("Descargar y verificar", icon="download", on_click=download_click).props("color=secondary")
            ui.button("Cancelar", icon="stop_circle", on_click=cancel_click).props("outline")

        refresh_sources()
        ctx.refresh_download_sources = refresh_sources


def _source_id(label: str, platform: str | None) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in label.strip().lower()).strip("-")
    return f"{safe or 'fuente'}-{platform or 'all'}"
