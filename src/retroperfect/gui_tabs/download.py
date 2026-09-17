"""Pestaña Descargar: fuentes propias, plan de lo que falta y descarga verificada."""
from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui

from ..dat import DatIndex
from ..download_plan import DownloadPlan, build_download_plan, human_size, resolve_remote_files
from ..downloader import collect_downloads, run_download_plan
from ..gui_context import UiContext
from ..gui_rows import _panel_class
from ..gui_state import _current_platform, _log_activity, busy, guarded, state
from ..gui_widgets import _data_table, _path_picker
from ..rom_sources import SOURCE_KIND_LABELS, RomSource, add_rom_source, list_rom_sources, remove_rom_source, set_rom_source_enabled, unique_source_id
from ..torrent_client import DEFAULT_URL as QBT_DEFAULT_URL
from ..torrent_client import QBittorrentClient, queue_plan


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
        sources_table = _data_table(
            columns=[
                {"name": "label", "label": "Fuente", "field": "label", "sortable": True, "align": "left"},
                {"name": "kind", "label": "Tipo", "field": "kind", "align": "left"},
                {"name": "location", "label": "Origen", "field": "location", "align": "left"},
                {"name": "platform", "label": "Plataforma", "field": "platform", "align": "center"},
                {"name": "enabled", "label": "Activa", "field": "enabled", "align": "center"},
            ],
            rows=[],
            row_key="id",
            selection="single",
            pagination=5,
        )

        with ui.row().classes("w-full items-end gap-2"):
            source_label = ui.input("Nombre").props("outlined dense").classes("w-56")
            source_kind = ui.select(SOURCE_KIND_LABELS, value="archive_org", label="Tipo").props("outlined dense").classes("w-96")
            source_location = ui.input("Ítem, URL o carpeta").props("outlined dense").classes("grow")
            only_this_platform = ui.checkbox("Solo esta plataforma", value=True)

        status = ui.label("Añade al menos una fuente para poder calcular qué falta.").classes("text-sm text-gray-600")

        def refresh_sources() -> None:
            sources = list_rom_sources()
            sources_table.rows = [
                {
                    "id": source.id,
                    "label": source.label,
                    "kind": source.kind,
                    "location": source.location,
                    "platform": source.platform or "todas",
                    "enabled": "sí" if source.enabled else "no",
                }
                for source in sources
            ]
            sources_table.update()
            # El panel de torrent solo estorba si no hay ninguna fuente de ese tipo.
            torrent_panel.visible = any(source.kind == "torrent" for source in sources)

        def add_source_click() -> None:
            if not source_label.value or not source_location.value:
                status.text = "Indica un nombre y el origen (ítem de archive.org, URL del índice o carpeta)."
                return
            platform = _current_platform().value if only_this_platform.value else None
            source_id = unique_source_id(_source_id(source_label.value, platform))
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

        def toggle_source_click() -> None:
            selected = sources_table.selected
            if not selected:
                status.text = "Selecciona la fuente que quieres activar o desactivar."
                return
            source = set_rom_source_enabled(selected[0]["id"], selected[0]["enabled"] == "no")
            sources_table.selected = []
            refresh_sources()
            status.text = f"{source.label}: {'activada' if source.enabled else 'desactivada'}."

        with ui.row():
            ui.button("Añadir fuente", icon="add_link", on_click=add_source_click).props("color=primary")
            ui.button("Activar/desactivar", icon="toggle_on", on_click=toggle_source_click).props("outline")
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

        ui.label("Marca filas para bajar solo esas; sin selección se descarga el plan entero.").classes("text-sm text-gray-600")
        plan_table = _data_table(
            columns=[
                {"name": "confidence", "label": "Coincidencia", "field": "confidence", "sortable": True, "align": "center"},
                {"name": "title", "label": "Juego", "field": "title", "sortable": True, "align": "left"},
                {"name": "file", "label": "Archivo remoto", "field": "file", "align": "left"},
                {"name": "size", "label": "Tamaño", "field": "size", "sortable": True, "align": "right"},
            ],
            rows=[],
            row_key="url",
            selection="multiple",
            pagination=15,
        )
        plan_table.add_slot(
            "body-cell-confidence",
            """
                <q-td :props="props" class="rp-center">
                  <q-badge v-if="props.value === 'hash'" color="green" label="HASH">
                    <q-tooltip>{{ props.row.confidence_label }}</q-tooltip>
                  </q-badge>
                  <q-badge v-else-if="props.value === 'name-exact'" color="blue" label="NOMBRE">
                    <q-tooltip>{{ props.row.confidence_label }}</q-tooltip>
                  </q-badge>
                  <q-badge v-else color="amber" text-color="black" label="APROX.">
                    <q-tooltip>{{ props.row.confidence_label }}</q-tooltip>
                  </q-badge>
                </q-td>
                """,
        )

        ui.label("Juegos que ninguna de tus fuentes ofrece").classes("text-md font-semibold")
        unavailable_table = _data_table(
            columns=[
                {"name": "title", "label": "Juego", "field": "title", "sortable": True, "align": "left"},
                {"name": "game", "label": "Entrada del DAT", "field": "game", "align": "left"},
            ],
            rows=[],
            pagination=5,
        )

        progress = ui.linear_progress(value=0.0, show_value=False).classes("w-full").props("instant-feedback")
        progress_label = ui.label("").classes("text-sm text-gray-600")
        progress.visible = False

        def refresh_plan_table() -> None:
            plan = holder["plan"]
            plan_table.selected = []
            plan_table.rows = (
                []
                if plan is None
                else [
                    {
                        "url": candidate.url,
                        "confidence": candidate.confidence,
                        "confidence_label": candidate.confidence_label,
                        "title": candidate.title,
                        "file": candidate.file_name,
                        "size": human_size(candidate.size),
                    }
                    for candidate in plan.candidates
                ]
            )
            plan_table.update()
            unavailable_table.rows = [] if plan is None else [{"title": missing.title, "game": missing.game_name} for missing in plan.unavailable]
            unavailable_table.update()

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
                    if not errors:
                        status.text = "Todas las fuentes de esta plataforma están desactivadas."
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
            unknown = plan.unknown_size_count
            metric_labels["size"].text = f"Tamaño: {human_size(plan.total_bytes)}" + (f" (+{unknown} sin tamaño)" if unknown else "")
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
            full_plan = holder["plan"]
            if full_plan is None or not full_plan.candidates:
                status.text = "Calcula primero un plan con candidatos."
                return
            destination = ctx.source.value
            if not destination:
                status.text = "Falta la carpeta del romset en Setup: es donde se instalará lo verificado."
                return
            plan = _selected_plan(full_plan, plan_table.selected)
            if not plan.candidates:
                status.text = "La selección no contiene ningún candidato."
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

        # --- Torrent -----------------------------------------------------------
        # La descarga la hace el cliente del usuario, pero elegir qué archivos y
        # verificar lo que llega tiene que poder hacerse aquí: la app empaquetada
        # no tiene terminal donde escribir `torrent-queue` ni `torrent-collect`.
        ui.separator()
        with ui.column().classes("w-full gap-2") as torrent_panel:
            ui.label("Torrent").classes("text-md font-semibold")
            ui.label(
                "RetroPerfect no descarga el torrent: eso lo hace tu cliente. Puede seleccionar por ti solo los archivos que te faltan "
                "(con qBittorrent, por su Web API) y, cuando tu cliente termine, verificar lo descargado e instalarlo en el romset."
            ).classes("text-sm text-gray-600")
            with ui.row().classes("w-full items-end gap-2"):
                qbt_url = ui.input("Web UI de qBittorrent", value=QBT_DEFAULT_URL).props("outlined dense").classes("w-72")
                downloads_dir = ui.input("Carpeta de descargas de tu cliente").props("outlined dense").classes("grow")
                downloads_dialog = _path_picker(downloads_dir, choose="directory")
            torrent_status = ui.label("").classes("text-sm text-gray-600")

            def _torrent_candidates(plan: DownloadPlan | None) -> list:
                return [candidate for candidate in plan.candidates if candidate.container == "torrent"] if plan else []

            def _plan_for_torrent() -> DownloadPlan | None:
                """Plan acotado a la selección y solo con sus candidatos de torrent."""
                full_plan = holder["plan"]
                if full_plan is None or not _torrent_candidates(full_plan):
                    torrent_status.text = "Calcula primero un plan que incluya archivos de un torrent."
                    return None
                selected = _selected_plan(full_plan, plan_table.selected)
                if not _torrent_candidates(selected):
                    torrent_status.text = "La selección no incluye ningún archivo de torrent."
                    return None
                return selected

            async def queue_click() -> None:
                plan = _plan_for_torrent()
                if plan is None:
                    return
                torrent_status.text = "Añadiendo a qBittorrent..."
                with guarded(torrent_status, "No se pudo encolar en qBittorrent", busy_label="encolado en qBittorrent"):
                    selected_files = 0
                    skipped_files = 0
                    locations = sorted({candidate.url for candidate in _torrent_candidates(plan)})
                    for location in locations:
                        result = await asyncio.to_thread(
                            queue_plan,
                            plan,
                            Path(location),
                            client=QBittorrentClient(qbt_url.value or QBT_DEFAULT_URL),
                            save_path=downloads_dir.value or None,
                        )
                        selected_files += result["seleccionados"]
                        skipped_files += result["descartados"]
                    torrent_status.text = (
                        f"Añadido a qBittorrent: {selected_files} archivos activos y {skipped_files} descartados "
                        f"en {len(locations)} torrent(s). Cuando termine, pulsa «Recoger lo descargado»."
                    )
                    _log_activity(f"Torrent encolado en qBittorrent: {selected_files} archivos seleccionados", "OK")

            async def collect_click() -> None:
                plan = _plan_for_torrent()
                if plan is None:
                    return
                if not downloads_dir.value:
                    torrent_status.text = "Indica la carpeta donde descarga tu cliente de torrent."
                    return
                destination = ctx.source.value
                if not destination:
                    torrent_status.text = "Falta la carpeta del romset en Setup: es donde se instalará lo verificado."
                    return
                torrent_status.text = "Verificando lo que tu cliente ya ha descargado..."
                with guarded(torrent_status, "No se pudo recoger lo descargado", busy_label="recogida de lo descargado"):
                    report = await asyncio.to_thread(
                        collect_downloads,
                        plan,
                        Path(downloads_dir.value),
                        Path(destination),
                        dat_index=DatIndex(state.catalog) if state.catalog else None,
                    )
                    counts: dict[str, int] = {}
                    for outcome in report.outcomes:
                        counts[outcome.status] = counts.get(outcome.status, 0) + 1
                    pending = " · ".join(f"{status}: {count}" for status, count in sorted(counts.items()) if status != "ok")
                    torrent_status.text = (
                        f"Instalados {report.downloaded} archivos verificados ({human_size(report.total_bytes)})."
                        + (f" Pendientes → {pending}." if pending else "")
                        + " Se copia, no se mueve: tu cliente sigue sembrando. Vuelve a escanear para incorporarlos."
                    )
                    for outcome in report.outcomes:
                        if outcome.status in {"mismatch", "incomplete"}:
                            _log_activity(f"{outcome.status_label}: {outcome.file_name}. {outcome.detail}", "WARN")
                    _log_activity(f"Torrent recogido: {report.downloaded} archivos instalados", "OK")

            with ui.row():
                ui.button("Buscar carpeta", icon="folder_open", on_click=downloads_dialog.open).props("outline")
                ui.button("Seleccionar en qBittorrent", icon="playlist_add", on_click=queue_click).props("color=primary")
                ui.button("Recoger lo descargado", icon="move_to_inbox", on_click=collect_click).props("color=secondary")

        refresh_sources()
        ctx.refresh_download_sources = refresh_sources


def _selected_plan(plan: DownloadPlan, selected_rows: list[dict] | None) -> DownloadPlan:
    """Acota el plan a las filas marcadas; sin selección se descarga entero."""
    urls = {row["url"] for row in selected_rows or []}
    if not urls:
        return plan
    return plan.model_copy(update={"candidates": [candidate for candidate in plan.candidates if candidate.url in urls]})


def _source_id(label: str, platform: str | None) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in label.strip().lower()).strip("-")
    return f"{safe or 'fuente'}-{platform or 'all'}"
