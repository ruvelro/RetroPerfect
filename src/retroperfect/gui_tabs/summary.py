"""Pestaña Resumen: auditoría de cobertura, avisos de DAT y cola de parches RA."""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from ..diagnostics import build_needed_rows, build_perfect_audit, detect_dat_warnings
from ..gui_context import UiContext
from ..gui_rows import (
    _coverage_rows,
    _coverage_variant_rows,
    _diagnostic_rows,
    _panel_class,
    _patch_queue_rows,
)
from ..gui_state import _current_platform, state


def build(ctx: UiContext) -> None:
    async def run_summary_plan_click() -> None:
        action = ctx.summary_actions.get("plan")
        if action is None:
            ui.notify("El plan aun no esta listo en la interfaz.", color="warning")
            return
        await action()

    async def run_summary_apply_click() -> None:
        action = ctx.summary_actions.get("apply")
        if action is None:
            ui.notify("El aplicador aun no esta listo en la interfaz.", color="warning")
            return
        await action()

    with ui.tab_panel(ctx.summary_tab).classes("p-0"), ui.column().classes(_panel_class()):
        ui.label("Cobertura del romset").classes("text-lg font-semibold")
        coverage_status = ui.label("Escanea una colección con DAT para validar titulos contra el DAT. El plan decide despues que se conserva.").classes("text-sm text-gray-600")
        with ui.grid().classes("w-full gap-3 grid-cols-2 md:grid-cols-4 xl:grid-cols-8"):
            audit_score = ui.label("Score: 0").classes("border border-gray-200 rounded-md p-3 text-center font-semibold")
            audit_verdict = ui.label("Pendiente").classes("border border-gray-200 rounded-md p-3 text-center")
            audit_complete = ui.label("Completos: 0").classes("border border-gray-200 rounded-md p-3 text-center")
            audit_missing = ui.label("Perdidos: 0").classes("border border-gray-200 rounded-md p-3 text-center")
            audit_duplicates = ui.label("Duplicados: 0").classes("border border-gray-200 rounded-md p-3 text-center")
            audit_ra = ui.label("RA: 0 / 0").classes("border border-gray-200 rounded-md p-3 text-center")
            audit_ra_missing = ui.label("Sin RA: 0").classes("border border-gray-200 rounded-md p-3 text-center")
            audit_patches = ui.label("Parches: 0").classes("border border-gray-200 rounded-md p-3 text-center")
        audit_notes = ui.label("La auditoría se calcula tras escanear y mejora al crear el plan.").classes("text-sm text-gray-600")
        ui.label("Avisos de DAT / romset").classes("text-md font-semibold")
        dat_warning_table = ui.table(
            columns=[
                {"name": "status", "label": "", "field": "status", "align": "center"},
                {"name": "item", "label": "Elemento", "field": "item", "sortable": True, "align": "left"},
                {"name": "detail", "label": "Detalle", "field": "detail", "align": "left"},
                {"name": "recommendation", "label": "Recomendación", "field": "recommendation", "align": "left"},
            ],
            rows=[],
            pagination=5,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table")
        dat_warning_table.add_slot(
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
        ui.label("Cola de parches RA").classes("text-md font-semibold")
        patch_queue_table = ui.table(
            columns=[
                {"name": "status", "label": "Estado", "field": "status", "sortable": True, "align": "center"},
                {"name": "game", "label": "Juego/hash RA", "field": "game", "align": "left"},
                {"name": "source", "label": "Base", "field": "source", "align": "left"},
                {"name": "patch", "label": "PatchUrl", "field": "patch", "align": "left"},
                {"name": "expected", "label": "MD5 final", "field": "expected", "align": "left"},
                {"name": "destination", "label": "Destino", "field": "destination", "align": "left"},
            ],
            rows=[],
            pagination=5,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table")
        with ui.row().classes("items-center gap-2 text-sm"):
            ui.badge("OK", color="green")
            ui.label("Coincide con DAT / se guardara")
            ui.badge("DROP", color="amber").props("text-color=black")
            ui.label("Coincide, pero el perfil lo descarta")
            ui.badge("MISS", color="red")
            ui.label("Falta en DAT o romset")
        with ui.row().classes("items-center gap-2 text-sm"):
            ui.label("Reglas:")
            ui.label("🎯 override")
            ui.label("🏆 RA/sin RA")
            ui.label("🏷️ tag")
            ui.label("🌍 región")
            ui.label("💬 idioma")
            ui.label("🔢 revisión")
            ui.label("✅ DAT")
        with ui.row().classes("items-center gap-2"):
            ui.button("Crear/actualizar plan", icon="rule", on_click=run_summary_plan_click).props("color=primary")
            ui.button("Aplicar plan revisado", icon="play_arrow", on_click=run_summary_apply_click).props("color=secondary outline")
        with ui.grid().classes("w-full gap-3 grid-cols-2 md:grid-cols-4 xl:grid-cols-8"):
            metric_dat = ui.label("DAT: 0").classes("border border-gray-200 rounded-md p-3 text-center")
            metric_rom = ui.label("Romset: 0").classes("border border-gray-200 rounded-md p-3 text-center")
            metric_match = ui.label("Coinciden: 0").classes("border border-gray-200 rounded-md p-3 text-center")
            metric_missing = ui.label("Faltan: 0").classes("border border-gray-200 rounded-md p-3 text-center")
            metric_unmatched = ui.label("Fuera DAT: 0").classes("border border-gray-200 rounded-md p-3 text-center")
            metric_hash = ui.label("Hash distinto: 0").classes("border border-gray-200 rounded-md p-3 text-center")
            metric_keep = ui.label("Se guardan: 0").classes("border border-gray-200 rounded-md p-3 text-center")
            metric_drop = ui.label("Se pierden: 0").classes("border border-gray-200 rounded-md p-3 text-center")
        coverage_filter = ui.select(
            {
                "all": "Todos los juegos",
                "complete_any_region": "Tengo el juego, cualquier región",
                "matched": "Coinciden con DAT",
                "missing": "Están en DAT y faltan",
                "unmatched": "Están en romset pero fuera del DAT",
                "hash_mismatch": "Están en DAT pero el hash no coincide",
                "will_drop": "Se perderán con el perfil actual",
            },
            value="all",
            label="Filtro",
        ).props("outlined").classes("w-96")
        coverage_view = ui.select(
            {"grouped": "Agrupado por juego", "variants": "Separado por variante/archivo"},
            value="grouped",
            label="Vista",
        ).props("outlined").classes("w-80")
        coverage_table = ui.table(
            columns=[
                {"name": "visual", "label": "", "field": "visual", "align": "center"},
                {"name": "title", "label": "Juego", "field": "title", "sortable": True, "align": "left"},
                {"name": "ra", "label": "RA", "field": "ra", "sortable": True, "align": "center"},
                {"name": "status", "label": "Estado", "field": "status", "sortable": True, "align": "center"},
                {"name": "variants", "label": "Variantes", "field": "variants", "sortable": True, "align": "left"},
                {"name": "dat_regions", "label": "DAT", "field": "dat_regions", "align": "center"},
                {"name": "rom_regions", "label": "Romset", "field": "rom_regions", "align": "center"},
                {"name": "keep", "label": "Salida", "field": "keep", "align": "center"},
                {"name": "reason", "label": "Regla", "field": "reason", "align": "center"},
            ],
            rows=[],
            pagination=20,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")
        coverage_table.add_slot(
            "body-cell-visual",
            """
                <q-td :props="props" class="rp-center">
                  <q-badge v-if="props.value === 'green'" color="green" label="OK" />
                  <q-badge v-else-if="props.value === 'yellow'" color="amber" text-color="black" label="DROP" />
                  <q-badge v-else-if="props.value === 'red'" color="red" label="MISS" />
                  <q-badge v-else color="grey" label="WAIT" />
                </q-td>
                """,
        )
        coverage_table.add_slot("body-cell-ra", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
        coverage_table.add_slot("body-cell-dat_regions", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
        coverage_table.add_slot("body-cell-rom_regions", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
        coverage_table.add_slot("body-cell-keep", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
        coverage_table.add_slot("body-cell-reason", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
        coverage_table.add_slot(
            "body-cell-title",
            """
                <q-td :props="props">
                  <strong :class="{
                    'text-green-700': props.row.visual === 'green',
                    'text-amber-800': props.row.visual === 'yellow',
                    'text-red-700': props.row.visual === 'red',
                    'text-grey-800': props.row.visual === 'neutral'
                  }">{{ props.value }}</strong>
                </q-td>
                """,
        )
        coverage_table.add_slot(
            "body-cell-status",
            """
                <q-td :props="props">
                  <span :class="{
                    'text-green-700': props.row.visual === 'green',
                    'text-amber-700': props.row.visual === 'yellow',
                    'text-red-700': props.row.visual === 'red',
                    'text-grey-700': props.row.visual === 'neutral'
                  }">{{ props.value }}</span>
                </q-td>
                """,
        )

        def refresh_coverage() -> None:
            summary = state.coverage
            if summary is None:
                coverage_table.rows = []
                coverage_table.update()
                audit = build_perfect_audit(None, None, None)
                audit_score.text = f"Score: {audit.score}"
                audit_verdict.text = audit.verdict
                audit_notes.text = " · ".join(audit.notes)
                dat_warning_table.rows = _diagnostic_rows(
                    build_needed_rows(
                        _current_platform(),
                        Path(ctx.source.value) if ctx.source.value else None,
                        Path(ctx.dat.value) if ctx.dat.value else None,
                        None,
                    )
                )
                dat_warning_table.update()
                patch_queue_table.rows = []
                patch_queue_table.update()
                return
            audit = build_perfect_audit(summary, state.scan, state.manifest)  # type: ignore[arg-type]
            audit_score.text = f"Score: {audit.score}"
            audit_verdict.text = audit.verdict
            audit_complete.text = f"Completos: {audit.complete_games}"
            audit_missing.text = f"Perdidos: {audit.missing_games}"
            audit_duplicates.text = f"Duplicados: {audit.duplicate_groups}"
            audit_ra.text = f"RA: {audit.ra_covered_games} / {summary.romset_games}"
            audit_ra_missing.text = f"Sin RA: {audit.ra_missing_games}"
            audit_patches.text = f"Parches: {audit.patch_pending}"
            audit_notes.text = " · ".join(audit.notes)
            dat_warning_table.rows = _diagnostic_rows(
                detect_dat_warnings(
                    _current_platform(),
                    Path(ctx.source.value) if ctx.source.value else None,
                    Path(ctx.dat.value) if ctx.dat.value else None,
                    state.scan,  # type: ignore[arg-type]
                )
            )
            dat_warning_table.update()
            patch_queue_table.rows = _patch_queue_rows(state.manifest)
            patch_queue_table.update()
            metric_dat.text = f"DAT: {summary.dat_games}"
            metric_rom.text = f"Romset: {summary.romset_games}"
            metric_match.text = f"Coinciden: {summary.matched_games}"
            metric_missing.text = f"Faltan: {summary.missing_from_romset}"
            metric_unmatched.text = f"Fuera DAT: {summary.unmatched_romset_games}"
            metric_hash.text = f"Hash distinto: {summary.hash_mismatch_games}"
            metric_keep.text = f"Se guardan: {summary.will_keep_games}"
            metric_drop.text = f"Se pierden: {summary.will_drop_all_games}"
            coverage_status.text = "Los titulos se validan al terminar el escaneo. Al crear el plan, los colores reflejan que se conserva o descarta."
            if coverage_view.value == "variants":
                coverage_table.rows = _coverage_variant_rows(state.scan, state.catalog, state.manifest, coverage_filter.value)
            else:
                coverage_table.rows = _coverage_rows(summary, coverage_filter.value, state.scan, state.manifest)
            coverage_table.update()

        coverage_filter.on_value_change(lambda _: refresh_coverage())
        coverage_view.on_value_change(lambda _: refresh_coverage())

    ctx.refresh_coverage = refresh_coverage
