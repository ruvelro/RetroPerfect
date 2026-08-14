"""Pestaña Plan: manifiesto, prueba segura, diálogo de seguridad y aplicación."""
from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui

from ..coverage import build_coverage
from ..gui_context import UiContext
from ..gui_rows import (
    ACTION_LABELS,
    _bucket_divergence_rows,
    _export_tree_rows,
    _panel_class,
    _plan_reason_icons,
    _profile_from_controls,
    _ra_conflict_rows,
    _scan_group_sample,
)
from ..gui_state import _log_activity, busy, state
from ..gui_widgets import _open_path
from ..manifest_io import apply_manifest, preflight_manifest, report_manifest, save_manifest
from ..models import ActionMode
from ..rules import build_manifest


def build(ctx: UiContext) -> None:
    with ui.tab_panel(ctx.plan_tab).classes("p-0"), ui.column().classes(_panel_class()):
        with ui.row().classes("items-center gap-3"):
            action = ui.select(ACTION_LABELS, value=ActionMode.COPY.value, label="Acción").props("outlined").classes("w-72")
            safe_sample_limit = ui.number("Prueba segura", value=25, min=1, max=200, step=5).props("outlined").classes("w-40")
            apply_confirm = ui.checkbox("He revisado el plan y autorizo aplicar cambios", value=False)
        plan_status = ui.label("El plan es la lista de operaciones que se guardará antes de copiar, mover o borrar. Primero créalo; después revísalo y aplica.").classes("text-sm text-gray-600")
        with ui.row().classes("items-center gap-2 text-sm"):
            ui.label("Leyenda:")
            ui.label("🎯 override")
            ui.label("✅ DAT")
            ui.label("🏆 RA")
            ui.label("🌍 región")
            ui.label("💬 idioma")
            ui.label("🔢 revisión")
        plan_table = ui.table(
            columns=[
                {"name": "bucket", "label": "Salida", "field": "bucket", "align": "center"},
                {"name": "source", "label": "Origen", "field": "source", "align": "left"},
                {"name": "destination", "label": "Destino", "field": "destination", "align": "left"},
                {"name": "icons", "label": "Motivo", "field": "icons", "align": "center"},
            ],
            rows=[],
            pagination=15,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")
        plan_table.add_slot("body-cell-bucket", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
        plan_table.add_slot("body-cell-icons", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
        ui.label("Main vs RetroAchievements").classes("text-md font-semibold")
        divergence_table = ui.table(
            columns=[
                {"name": "game", "label": "Juego", "field": "game", "sortable": True, "align": "left"},
                {"name": "main", "label": "Main", "field": "main", "align": "left"},
                {"name": "ra", "label": "RA", "field": "ra", "align": "left"},
                {"name": "state", "label": "Relación", "field": "state", "sortable": True, "align": "center"},
            ],
            rows=[],
            pagination=8,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")
        divergence_table.add_slot("body-cell-state", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
        ui.label("Conflictos RetroAchievements").classes("text-md font-semibold")
        ra_conflict_table = ui.table(
            columns=[
                {"name": "game", "label": "Juego", "field": "game", "sortable": True, "align": "left"},
                {"name": "main", "label": "Main elegido", "field": "main", "align": "left"},
                {"name": "ra", "label": "Variante RA", "field": "ra", "align": "left"},
                {"name": "state", "label": "Estado", "field": "state", "sortable": True, "align": "center"},
            ],
            rows=[],
            pagination=8,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")
        ra_conflict_table.add_slot("body-cell-state", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
        ui.label("Simulación de salida").classes("text-md font-semibold")
        export_tree_table = ui.table(
            columns=[
                {"name": "folder", "label": "Carpeta", "field": "folder", "sortable": True, "align": "left"},
                {"name": "files", "label": "Archivos", "field": "files", "sortable": True, "align": "right"},
                {"name": "main", "label": "Main", "field": "main", "sortable": True, "align": "right"},
                {"name": "ra", "label": "RA", "field": "ra", "sortable": True, "align": "right"},
                {"name": "patches", "label": "Parches", "field": "patches", "sortable": True, "align": "right"},
            ],
            rows=[],
            pagination=8,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")

        safety_dialog = ui.dialog()
        with safety_dialog, ui.card().classes("w-[760px] max-w-[95vw]"):
            ui.label("Revisión final antes de aplicar").classes("text-lg font-semibold")
            safety_summary = ui.label().classes("text-sm text-gray-700")
            safety_paths = ui.textarea("Archivos afectados").props("readonly rows=10 outlined").classes("w-full")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancelar", icon="close", on_click=safety_dialog.close).props("flat")

                async def confirm_apply_click() -> None:
                    manifest = state.manifest
                    if manifest is None:
                        plan_status.text = "No hay manifiesto que aplicar."
                        safety_dialog.close()
                        return
                    try:
                        with busy("aplicando el manifiesto"):
                            completed = await asyncio.to_thread(apply_manifest, manifest, None, True)  # type: ignore[arg-type]
                        plan_status.text = f"Aplicadas {len(completed)} operaciones."
                        safety_dialog.close()
                    except Exception as exc:
                        plan_status.text = f"No se aplicó: {exc}"
                        safety_dialog.close()

                ui.button("Aplicar manifiesto", icon="play_arrow", on_click=confirm_apply_click).props("color=secondary")

        async def plan_click() -> None:
            scan_result = state.scan
            if scan_result is None:
                plan_status.text = "Escanea una colección antes de crear el plan."
                return
            try:
                state.profile = _profile_from_controls(ctx.controls)
                profile = state.profile
                manifest = build_manifest(
                    scan_result,  # type: ignore[arg-type]
                    profile,  # type: ignore[arg-type]
                    [output.bucket for output in profile.outputs],  # type: ignore[attr-defined]
                    output_dir=Path(ctx.outdir.value) if ctx.outdir.value else None,
                    action=ActionMode(action.value),
                    overrides=state.overrides,  # type: ignore[arg-type]
                )
                path = save_manifest(manifest, Path(".retroperfect/manifests/latest.json"))
                state.manifest = manifest
                state.coverage = build_coverage(scan_result, state.catalog, manifest)  # type: ignore[arg-type]
                ctx.update_tab_access()
                plan_table.rows = [
                    {
                        "bucket": entry.bucket.value,
                        "source": Path(entry.source_path).name,
                        "destination": str(Path(entry.destination_path).relative_to(Path(ctx.outdir.value))) if entry.destination_path and ctx.outdir.value else (entry.destination_path or ""),
                        "icons": _plan_reason_icons(entry.explanation),
                    }
                    for entry in manifest.entries
                ]
                plan_table.update()
                divergence_table.rows = _bucket_divergence_rows(scan_result, manifest)
                divergence_table.update()
                ra_conflict_table.rows = _ra_conflict_rows(scan_result, manifest)
                ra_conflict_table.update()
                export_tree_table.rows = _export_tree_rows(manifest, ctx.outdir.value)
                export_tree_table.update()
                plan_status.text = f"Manifiesto guardado en {path}"
                ctx.refresh_coverage()
            except Exception as exc:
                plan_status.text = f"Error creando plan: {exc}"

        async def safe_plan_click() -> None:
            scan_result = state.scan
            if scan_result is None:
                plan_status.text = "Escanea una colección antes de crear una prueba segura."
                return
            if not ctx.outdir.value:
                plan_status.text = "El modo prueba segura necesita carpeta de salida."
                return
            try:
                sample = _scan_group_sample(scan_result, int(safe_sample_limit.value or 25))
                if sample is None:
                    plan_status.text = "No hay datos de escaneo para muestrear."
                    return
                state.profile = _profile_from_controls(ctx.controls)
                profile = state.profile
                manifest = build_manifest(
                    sample,
                    profile,  # type: ignore[arg-type]
                    [output.bucket for output in profile.outputs],  # type: ignore[attr-defined]
                    output_dir=Path(ctx.outdir.value) / "_prueba_segura",
                    action=ActionMode.COPY,
                    overrides=state.overrides,  # type: ignore[arg-type]
                )
                path = save_manifest(manifest, Path(".retroperfect/manifests/latest-safe-sample.json"))
                state.manifest = manifest
                state.coverage = build_coverage(scan_result, state.catalog, manifest)  # type: ignore[arg-type]
                action.value = ActionMode.COPY.value
                action.update()
                plan_table.rows = [
                    {
                        "bucket": entry.bucket.value,
                        "source": Path(entry.source_path).name,
                        "destination": str(Path(entry.destination_path).relative_to(Path(ctx.outdir.value))) if entry.destination_path and ctx.outdir.value else (entry.destination_path or ""),
                        "icons": _plan_reason_icons(entry.explanation),
                    }
                    for entry in manifest.entries
                ]
                plan_table.update()
                divergence_table.rows = _bucket_divergence_rows(sample, manifest)
                divergence_table.update()
                ra_conflict_table.rows = _ra_conflict_rows(sample, manifest)
                ra_conflict_table.update()
                export_tree_table.rows = _export_tree_rows(manifest, ctx.outdir.value)
                export_tree_table.update()
                ctx.update_tab_access()
                ctx.refresh_coverage()
                _log_activity(f"Prueba segura creada: {len(manifest.entries)} operaciones", "OK")
                plan_status.text = f"Prueba segura guardada en {path}. Solo copia en _prueba_segura."
            except Exception as exc:
                plan_status.text = f"Error creando prueba segura: {exc}"

        async def apply_click() -> None:
            manifest = state.manifest
            if manifest is None:
                plan_status.text = "No hay manifiesto que aplicar."
                return
            if not apply_confirm.value:
                plan_status.text = "Marca la confirmación tras revisar el manifiesto."
                return
            issues = await asyncio.to_thread(preflight_manifest, manifest)
            if issues:
                plan_status.text = "Problemas antes de aplicar: " + " · ".join(issues)
                _log_activity(f"Preflight de aplicar con {len(issues)} problema(s)", "WARN")
                return
            counts = {mode.value: 0 for mode in ActionMode}
            for entry in manifest.entries:  # type: ignore[union-attr]
                counts[entry.action.value] += 1
            destructive = bool(counts[ActionMode.MOVE.value] or counts[ActionMode.DELETE.value])
            safety_summary.text = (
                f"Se aplicará la acción planificada de cada entrada. Operaciones: {len(manifest.entries)}. "
                f"Copiar: {counts['copy']} · Mover: {counts['move']} · Borrar: {counts['delete']}. "
                f"{'Esta operación tocará archivos originales.' if destructive else 'Esta operación copiará a destino.'}"
            )
            safety_paths.value = "\n".join(
                f"{entry.bucket.value}: {entry.source_path} -> {entry.destination_path or '[sin destino]'}"
                for entry in manifest.entries  # type: ignore[union-attr]
            )
            safety_dialog.open()

        async def report_click() -> None:
            manifest = state.manifest
            if manifest is None:
                plan_status.text = "No hay manifiesto para reportar."
                return
            path = report_manifest(manifest, Path(".retroperfect/reports/latest.html"), "html")  # type: ignore[arg-type]
            plan_status.text = f"Reporte generado en {path}"

        ctx.summary_actions["plan"] = plan_click
        ctx.summary_actions["apply"] = apply_click

        with ui.row():
            ui.button("Crear manifiesto", icon="rule", on_click=plan_click).props("color=primary")
            ui.button("Crear prueba segura", icon="science", on_click=safe_plan_click).props("outline")
            ui.button("Generar reporte", icon="article", on_click=report_click).props("outline")
            ui.button("Abrir salida", icon="folder_open", on_click=lambda: _open_path(ctx.outdir.value)).props("outline")
            ui.button("Abrir reportes", icon="topic", on_click=lambda: _open_path(Path(".retroperfect/reports"))).props("outline")
            ui.button("Abrir papelera", icon="delete_sweep", on_click=lambda: _open_path(Path(".retroperfect/trash"))).props("outline")
            ui.button("Aplicar", icon="play_arrow", on_click=apply_click).props("color=secondary")
