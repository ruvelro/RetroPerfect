"""Pestaña Plan: manifiesto, prueba segura, diálogo de seguridad y aplicación."""
from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path

from nicegui import ui

from ..coverage import build_coverage
from ..device_sync import parse_budget, plan_device_sync, sync_order_labels
from ..download_plan import human_size
from ..gui_context import UiContext
from ..gui_rows import (
    _bucket_divergence_rows,
    _export_tree_rows,
    _panel_class,
    _plan_reason_icons,
    _profile_from_controls,
    _ra_conflict_rows,
    _scan_group_sample,
    action_labels,
    container_labels,
)
from ..gui_state import _log_activity, busy, guarded, state
from ..gui_widgets import MAX_FILAS_TABLA, _data_table, _limitar_filas, _open_path, _path_picker
from ..i18n import _
from ..manifest_io import apply_manifest, blocking_issues, report_manifest, save_manifest
from ..models import ActionMode, ContainerMode, Manifest
from ..paths import project_state_dir
from ..rules import build_manifest


def build(ctx: UiContext) -> None:
    cancel_flag = {"cancelled": False}
    with ui.tab_panel(ctx.plan_tab).classes("p-0"), ui.column().classes(_panel_class()):
        with ui.row().classes("items-center gap-3"):
            action = ui.select(action_labels(), value=ActionMode.COPY.value, label=_("Acción")).props("outlined").classes("w-72")
            containers = ui.select(container_labels(), value=ContainerMode.KEEP.value, label=_("ZIP y 7z")).props("outlined").classes("w-80")
            containers.tooltip(_("Copiar el contenedor entero se lleva también los descartes que haya dentro. Extraer deja la ROM suelta; reempaquetar escribe un ZIP por juego con solo lo que se conserva, con los nombres del DAT."))
            safe_sample_limit = ui.number(_("Prueba segura"), value=25, min=1, max=200, step=5).props("outlined").classes("w-40")
            apply_confirm = ui.checkbox(_("He revisado el plan y autorizo aplicar cambios"), value=False)
            use_link = ui.checkbox(_("Enlazar en vez de copiar (mismo disco)"), value=False)
            use_link.tooltip(_("Crea enlaces duros: la colección curada no ocupa espacio extra. Solo funciona si origen y destino están en la misma unidad; si no, se copia igualmente."))
            use_overwrite = ui.checkbox(_("Reemplazar lo que ya haya en el destino"), value=False)
            use_overwrite.tooltip(_("Por defecto, si en la salida ya existe un archivo distinto con ese nombre, la aplicación se detiene sin tocar nada. Marca esto para sustituirlo."))
        plan_status = ui.label(_("El plan es la lista de operaciones que se guardará antes de copiar, mover o borrar. Primero créalo; después revísalo y aplica.")).classes("text-sm text-gray-600")
        apply_progress = ui.linear_progress(value=0, show_value=False).props("instant-feedback").classes("w-full")
        apply_progress_label = ui.label("").classes("text-xs text-gray-500")
        apply_progress.visible = False

        def refresh_apply_progress() -> None:
            avance = state.apply_progress
            total = int(avance.get("total", 0) or 0)
            current = int(avance.get("current", 0) or 0)
            apply_progress.value = current / total if total else 0
            destino = str(avance.get("path", "") or "")
            apply_progress_label.text = f"{current} / {total} operaciones · {Path(destino).name}" if total else ""
        with ui.row().classes("items-center gap-2 text-sm"):
            ui.label(_("Leyenda:"))
            ui.label(_("🎯 override"))
            ui.label(_("✅ DAT"))
            ui.label(_("🏆 RA"))
            ui.label(_("🌍 región"))
            ui.label(_("💬 idioma"))
            ui.label(_("🔢 revisión"))
        plan_table = _data_table(
            columns=[
                {"name": "bucket", "label": _("Salida"), "field": "bucket", "align": "center"},
                {"name": "source", "label": _("Origen"), "field": "source", "align": "left"},
                {"name": "destination", "label": _("Destino"), "field": "destination", "align": "left"},
                {"name": "icons", "label": _("Motivo"), "field": "icons", "align": "center"},
            ],
            rows=[],
            pagination=15,
        )
        ui.label(_("Main vs RetroAchievements")).classes("text-md font-semibold")
        divergence_table = _data_table(
            columns=[
                {"name": "game", "label": _("Juego"), "field": "game", "sortable": True, "align": "left"},
                {"name": "main", "label": _("Main"), "field": "main", "align": "left"},
                {"name": "ra", "label": _("RA"), "field": "ra", "align": "left"},
                {"name": "state", "label": _("Relación"), "field": "state", "sortable": True, "align": "center"},
            ],
            rows=[],
            pagination=8,
        )
        ui.label(_("Conflictos RetroAchievements")).classes("text-md font-semibold")
        ra_conflict_table = _data_table(
            columns=[
                {"name": "game", "label": _("Juego"), "field": "game", "sortable": True, "align": "left"},
                {"name": "main", "label": _("Main elegido"), "field": "main", "align": "left"},
                {"name": "ra", "label": _("Variante RA"), "field": "ra", "align": "left"},
                {"name": "state", "label": _("Estado"), "field": "state", "sortable": True, "align": "center"},
            ],
            rows=[],
            pagination=8,
        )
        ui.label(_("Simulación de salida")).classes("text-md font-semibold")
        export_tree_table = _data_table(
            columns=[
                {"name": "folder", "label": _("Carpeta"), "field": "folder", "sortable": True, "align": "left"},
                {"name": "files", "label": _("Archivos"), "field": "files", "sortable": True, "align": "right"},
                {"name": "main", "label": _("Main"), "field": "main", "sortable": True, "align": "right"},
                {"name": "ra", "label": _("RA"), "field": "ra", "sortable": True, "align": "right"},
                {"name": "patches", "label": _("Parches"), "field": "patches", "sortable": True, "align": "right"},
            ],
            rows=[],
            pagination=8,
        )

        def repintar_tablas(scan, manifest) -> str:
            """Vuelca el manifiesto en las cuatro tablas y devuelve el aviso de recorte.

            Lo usan el plan completo y la prueba segura, que repetían este
            bloque entero: cuando se añadió el recorte de filas hubo que
            tocarlo en los dos sitios, y así es cuestión de tiempo que uno se
            quede atrás.
            """
            plan_table.rows, recorte = _limitar_filas(
                [
                    {
                        "bucket": entry.bucket.value,
                        "source": Path(entry.source_path).name,
                        "destination": str(Path(entry.destination_path).relative_to(Path(ctx.outdir.value))) if entry.destination_path and ctx.outdir.value else (entry.destination_path or ""),
                        "icons": _plan_reason_icons(entry.explanation),
                    }
                    for entry in manifest.entries
                ]
            )
            plan_table.update()
            divergence_table.rows = _bucket_divergence_rows(scan, manifest)
            divergence_table.update()
            ra_conflict_table.rows = _ra_conflict_rows(scan, manifest)
            ra_conflict_table.update()
            export_tree_table.rows = _export_tree_rows(manifest, ctx.outdir.value)
            export_tree_table.update()
            return recorte

        safety_dialog = ui.dialog()
        with safety_dialog, ui.card().classes("w-[760px] max-w-[95vw]"):
            ui.label(_("Revisión final antes de aplicar")).classes("text-lg font-semibold")
            safety_summary = ui.label().classes("text-sm text-gray-700")
            safety_paths = ui.textarea(_("Archivos afectados")).props("readonly rows=10 outlined").classes("w-full")
            with ui.row().classes("justify-end w-full"):
                ui.button(_("Cancelar"), icon="close", on_click=safety_dialog.close).props("flat")

                async def confirm_apply_click() -> None:
                    manifest = state.manifest
                    if manifest is None:
                        plan_status.text = _("No hay manifiesto que aplicar.")
                        safety_dialog.close()
                        return
                    safety_dialog.close()
                    cancel_flag["cancelled"] = False
                    state.apply_progress = {"current": 0, "total": len(manifest.entries), "path": "", "phase": "start"}
                    apply_progress.visible = True
                    with guarded(plan_status, "No se aplicó", busy_label="aplicando el manifiesto"):
                        # El hilo solo escribe en el estado; los widgets los
                        # refresca este handler mientras espera, para no tocar
                        # la UI desde otro hilo.
                        def on_progress(event: dict[str, object]) -> None:
                            state.apply_progress = event

                        task = asyncio.create_task(
                            asyncio.to_thread(
                                partial(
                                    apply_manifest,
                                    manifest,
                                    None,
                                    True,
                                    link=use_link.value,
                                    overwrite=use_overwrite.value,
                                    progress=on_progress,
                                    cancelled=lambda: cancel_flag["cancelled"],
                                )
                            )
                        )
                        while not task.done():
                            await asyncio.sleep(0.2)
                            refresh_apply_progress()
                        completed = await task
                        refresh_apply_progress()
                        if cancel_flag["cancelled"]:
                            plan_status.text = f"Aplicación cancelada: {len(completed)} operaciones hechas, el resto sin tocar. Vuelve a aplicar para continuar."
                            _log_activity(f"Aplicación cancelada por el usuario tras {len(completed)} operaciones", "WARN")
                        else:
                            plan_status.text = f"Aplicadas {len(completed)} operaciones."
                    apply_progress.visible = False
                    state.apply_progress = {"current": 0, "total": 0, "path": "", "phase": "idle"}

                ui.button(_("Aplicar manifiesto"), icon="play_arrow", on_click=confirm_apply_click).props("color=secondary")

        async def plan_click() -> None:
            scan_result = state.scan
            if scan_result is None:
                plan_status.text = _("Escanea una colección antes de crear el plan.")
                return
            with guarded(plan_status, "Error creando plan", busy_label="creación del plan"):
                state.profile = _profile_from_controls(ctx.controls)
                profile = state.profile
                manifest = build_manifest(
                    scan_result,
                    profile,
                    [output.bucket for output in profile.outputs],
                    output_dir=Path(ctx.outdir.value) if ctx.outdir.value else None,
                    action=ActionMode(action.value),
                    overrides=state.overrides,
                    container_mode=ContainerMode(containers.value),
                )
                path = save_manifest(manifest, project_state_dir() / "manifests" / "latest.json")
                state.manifest = manifest
                state.coverage = build_coverage(scan_result, state.catalog, manifest)
                ctx.update_tab_access()
                recorte = repintar_tablas(scan_result, manifest)
                playlists = f" · {len(manifest.playlists)} playlist(s) .m3u para juegos de varios discos" if manifest.playlists else ""
                playlists += f" · {len(manifest.archives)} ZIP por juego" if manifest.archives else ""
                plan_status.text = f"Manifiesto guardado en {path}{playlists}{recorte}"
                ctx.refresh_coverage()

        async def safe_plan_click() -> None:
            scan_result = state.scan
            if scan_result is None:
                plan_status.text = _("Escanea una colección antes de crear una prueba segura.")
                return
            if not ctx.outdir.value:
                plan_status.text = _("El modo prueba segura necesita carpeta de salida.")
                return
            with guarded(plan_status, "Error creando prueba segura", busy_label="creación de la prueba segura"):
                sample = _scan_group_sample(scan_result, int(safe_sample_limit.value or 25))
                if sample is None:
                    plan_status.text = _("No hay datos de escaneo para muestrear.")
                    return
                state.profile = _profile_from_controls(ctx.controls)
                profile = state.profile
                manifest = build_manifest(
                    sample,
                    profile,
                    [output.bucket for output in profile.outputs],
                    output_dir=Path(ctx.outdir.value) / "_prueba_segura",
                    action=ActionMode.COPY,
                    overrides=state.overrides,
                    container_mode=ContainerMode(containers.value),
                )
                path = save_manifest(manifest, project_state_dir() / "manifests" / "latest-safe-sample.json")
                state.manifest = manifest
                state.coverage = build_coverage(scan_result, state.catalog, manifest)
                action.value = ActionMode.COPY.value
                action.update()
                recorte = repintar_tablas(sample, manifest)
                ctx.update_tab_access()
                ctx.refresh_coverage()
                _log_activity(f"Prueba segura creada: {len(manifest.entries)} operaciones", "OK")
                plan_status.text = f"Prueba segura guardada en {path}. Solo copia en _prueba_segura.{recorte}"

        async def apply_click() -> None:
            manifest = state.manifest
            if manifest is None:
                plan_status.text = _("No hay manifiesto que aplicar.")
                return
            if not apply_confirm.value:
                plan_status.text = _("Marca la confirmación tras revisar el manifiesto.")
                return
            with busy("comprobaciones previas"):
                issues = await asyncio.to_thread(blocking_issues, manifest, use_overwrite.value)
            if issues:
                plan_status.text = "Problemas antes de aplicar: " + " · ".join(issues)
                _log_activity(f"Preflight de aplicar con {len(issues)} problema(s)", "WARN")
                return
            counts = {mode.value: 0 for mode in ActionMode}
            for entry in manifest.entries:
                counts[entry.action.value] += 1
            destructive = bool(counts[ActionMode.MOVE.value] or counts[ActionMode.DELETE.value])
            safety_summary.text = (
                f"Se aplicará la acción planificada de cada entrada. Operaciones: {len(manifest.entries)}. "
                f"Copiar: {counts['copy']} · Mover: {counts['move']} · Borrar: {counts['delete']}. "
                f"{'Esta operación tocará archivos originales.' if destructive else 'Esta operación copiará a destino.'}"
            )
            lineas = [
                f"{entry.bucket.value}: {entry.source_path} -> {entry.destination_path or '[sin destino]'}"
                for entry in manifest.entries
            ]
            # El cuadro es para revisar una muestra antes de autorizar; la lista
            # completa está en el manifiesto y en el informe.
            if len(lineas) > MAX_FILAS_TABLA:
                lineas = [*lineas[:MAX_FILAS_TABLA], f"… y {len(manifest.entries) - MAX_FILAS_TABLA} operaciones más (revísalas en el informe)"]
            safety_paths.value = "\n".join(lineas)
            safety_dialog.open()

        async def report_click() -> None:
            manifest = state.manifest
            if manifest is None:
                plan_status.text = _("No hay manifiesto para reportar.")
                return
            path = report_manifest(manifest, project_state_dir() / "reports" / "latest.html", "html")
            plan_status.text = f"Reporte generado en {path}"

        ctx.summary_actions["plan"] = plan_click
        ctx.summary_actions["apply"] = apply_click

        with ui.row():
            ui.button(_("Crear manifiesto"), icon="rule", on_click=plan_click).props("color=primary")
            ui.button(_("Crear prueba segura"), icon="science", on_click=safe_plan_click).props("outline")
            ui.button(_("Generar reporte"), icon="article", on_click=report_click).props("outline")
            ui.button(_("Abrir salida"), icon="folder_open", on_click=lambda: _open_path(ctx.outdir.value)).props("outline")
            ui.button(_("Abrir reportes"), icon="topic", on_click=lambda: _open_path(project_state_dir() / "reports")).props("outline")
            ui.button(_("Aplicar"), icon="play_arrow", on_click=apply_click).props("color=secondary")

            def cancel_apply_click() -> None:
                cancel_flag["cancelled"] = True
                plan_status.text = _("Cancelando tras la operación en curso...")

            ui.button(_("Cancelar"), icon="stop_circle", on_click=cancel_apply_click).props("outline")

        # --- Dispositivo -------------------------------------------------------
        # Llenar una SD o una consola es un plan acotado por tamaño, no otro
        # camino: se recorta este mismo manifiesto y se aplica igual, con su
        # verificación y su papelera. Tiene que poder hacerse aquí: la app
        # empaquetada no tiene terminal donde escribir `sync-device`.
        ui.separator()
        ui.label(_("Llenar un dispositivo")).classes("text-md font-semibold")
        ui.label(_("Copia lo que quepa en una SD, una consola o un disco sin pasarse del tamaño. Un juego de varios discos entra entero o no entra: medio juego ocupa sitio y no se puede terminar.")).classes("text-sm text-gray-600")
        device_status = ui.label("").classes("text-sm text-gray-600")
        with ui.row().classes("items-center gap-3"):
            device_dest = ui.input(_("Carpeta del dispositivo")).props("outlined readonly").classes("w-96")
            device_dialog = _path_picker(device_dest, choose="directory")
            ui.button(_("Elegir"), icon="sd_card", on_click=device_dialog.open).props("outline")
            device_budget = ui.input(_("Cabe"), value="32GB").props("outlined").classes("w-40")
            device_budget.tooltip(_("32GB, 512MiB o el número de bytes. Las tarjetas se venden en GB decimales y el sistema las mide en GiB, así que se admiten las dos."))
            device_order = ui.select(sync_order_labels(), value="size", label=_("Orden")).props("outlined").classes("w-96")
        device_table = _data_table(
            columns=[
                {"name": "title", "label": _("Juego"), "field": "title", "sortable": True, "align": "left"},
                {"name": "size", "label": _("Tamaño"), "field": "size", "sortable": True, "align": "right"},
                {"name": "files", "label": _("Archivos"), "field": "files", "align": "right"},
                {"name": "ra", "label": _("RA"), "field": "ra", "align": "center"},
            ],
            rows=[],
            pagination=8,
        )
        device_plan: dict[str, Manifest | None] = {"manifest": None}

        def device_plan_click() -> None:
            scan_result = state.scan
            if scan_result is None:
                device_status.text = _("Escanea una colección antes de llenar un dispositivo.")
                return
            if not device_dest.value:
                device_status.text = _("Elige la carpeta del dispositivo.")
                return
            with guarded(device_status, "Error calculando el plan del dispositivo", busy_label="plan del dispositivo"):
                presupuesto = parse_budget(str(device_budget.value or ""))
                state.profile = _profile_from_controls(ctx.controls)
                completo = build_manifest(
                    scan_result,
                    state.profile,
                    [output.bucket for output in state.profile.outputs],
                    output_dir=Path(device_dest.value),
                    action=ActionMode.COPY,
                    overrides=state.overrides,
                    container_mode=ContainerMode(containers.value),
                )
                manifest, report = plan_device_sync(completo, scan_result, Path(device_dest.value), presupuesto, str(device_order.value))
                device_plan["manifest"] = manifest
                device_table.rows, recorte = _limitar_filas(
                    [
                        {"title": juego.title, "size": human_size(juego.size), "files": juego.files, "ra": "🏆" if juego.ra else ""}
                        for juego in report.included
                    ]
                )
                device_table.update()
                fuera = f" Se quedan fuera {len(report.excluded)}." if report.excluded else ""
                device_status.text = (
                    f"Entran {len(report.included)} juego(s): {human_size(report.bytes_planned)}, "
                    f"quedan {human_size(report.bytes_left)} libres.{fuera}{recorte}"
                )

        async def device_sync_click() -> None:
            manifest = device_plan["manifest"]
            if manifest is None:
                device_status.text = _("Calcula primero qué cabe en el dispositivo.")
                return
            with guarded(device_status, "No se sincronizó", busy_label="sincronización con el dispositivo"):
                completed = await asyncio.to_thread(partial(apply_manifest, manifest, None, True, link=use_link.value, overwrite=use_overwrite.value))
                _log_activity(f"Dispositivo sincronizado: {len(completed)} operaciones en {device_dest.value}", "OK")
                device_status.text = f"{len(completed)} operación(es) en {device_dest.value}. Lo que ya estaba y no había cambiado se omitió."

        with ui.row():
            ui.button(_("Calcular qué cabe"), icon="straighten", on_click=device_plan_click).props("color=primary")
            ui.button(_("Sincronizar dispositivo"), icon="sd_card", on_click=device_sync_click).props("color=secondary")

        ui.label(_("Lo que se borre va a la papelera, restaurable desde la pestaña Actividad.")).classes("text-sm text-gray-600")
