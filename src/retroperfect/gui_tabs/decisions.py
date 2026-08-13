"""Pestaña Decisiones: variantes por juego y overrides manuales."""
from __future__ import annotations

from nicegui import ui

from ..gui_context import UiContext
from ..gui_rows import (
    _panel_class,
)
from ..gui_state import _group_rows, _variant_rows, state


def build(ctx: UiContext) -> None:
    with ui.tab_panel(ctx.decisions_tab).classes("p-0"), ui.column().classes(_panel_class()):
        ui.label("Decisiones por juego").classes("text-lg font-semibold")
        decision_status = ui.label("Escanea una colección para revisar variantes.").classes("text-sm text-gray-600")
        with ui.row().classes("items-center gap-2 text-sm"):
            ui.label("Leyenda:")
            ui.label("✅ DAT")
            ui.label("❌ sin DAT")
            ui.label("🏆 RA")
            ui.label("🎯 override")
            ui.label("🌍 región")
            ui.label("💬 idioma")
            ui.label("🔢 revisión")
        selected_group = {"key": ""}
        with ui.grid(columns=2).classes("w-full gap-4"):
            groups_table = ui.table(
                columns=[
                    {"name": "title", "label": "Juego", "field": "title", "sortable": True, "align": "left"},
                    {"name": "variants", "label": "Variantes", "field": "variants", "sortable": True, "align": "right"},
                    {"name": "regions", "label": "Regiones", "field": "regions", "align": "center"},
                    {"name": "ra", "label": "RA", "field": "ra", "sortable": True, "align": "center"},
                    {"name": "main_override", "label": "Main fijo", "field": "main_override", "align": "left"},
                    {"name": "ra_override", "label": "RA fijo", "field": "ra_override", "align": "left"},
                ],
                rows=[],
                row_key="group",
                pagination=12,
            ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")
            variants_table = ui.table(
                columns=[
                    {"name": "choice", "label": "Fijado", "field": "choice", "align": "center"},
                    {"name": "dat", "label": "DAT", "field": "dat", "align": "center"},
                    {"name": "file", "label": "Archivo", "field": "file", "sortable": True, "align": "left"},
                    {"name": "regions", "label": "Región", "field": "regions", "align": "center"},
                    {"name": "revision", "label": "Rev", "field": "revision", "align": "center"},
                    {"name": "ra", "label": "RA", "field": "ra", "align": "center"},
                    {"name": "tags", "label": "Tags", "field": "tags", "align": "right"},
                    {"name": "priority", "label": "Prioridad", "field": "priority", "align": "center"},
                ],
                rows=[],
                row_key="id",
                selection="single",
                pagination=8,
            ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")
            groups_table.add_slot("body-cell-regions", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
            groups_table.add_slot("body-cell-ra", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
            variants_table.add_slot("body-cell-choice", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
            variants_table.add_slot("body-cell-dat", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
            variants_table.add_slot("body-cell-regions", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
            variants_table.add_slot("body-cell-revision", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
            variants_table.add_slot("body-cell-ra", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
            variants_table.add_slot("body-cell-tags", '<q-td :props="props" class="rp-right">{{ props.value }}</q-td>')
            variants_table.add_slot("body-cell-priority", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')

        def refresh_decisions() -> None:
            groups_table.rows = _group_rows(state.scan)
            groups_table.update()
            if selected_group["key"]:
                variants_table.rows = _variant_rows(state.scan, selected_group["key"], state.profile)  # type: ignore[arg-type]
                variants_table.update()

        def select_group(event) -> None:
            row = event.args[1] if isinstance(event.args, list) and len(event.args) > 1 else event.args
            selected_group["key"] = row.get("group", "") if isinstance(row, dict) else ""
            variants_table.rows = _variant_rows(state.scan, selected_group["key"], state.profile)  # type: ignore[arg-type]
            variants_table.update()
            decision_status.text = f"Revisando: {row.get('title', selected_group['key']) if isinstance(row, dict) else selected_group['key']}"

        groups_table.on("rowClick", select_group)

        def selected_variant_id() -> str | None:
            selected = variants_table.selected
            if not selected:
                return None
            return selected[0].get("id")

        def set_override(bucket: str) -> None:
            rom_id = selected_variant_id()
            if not selected_group["key"] or not rom_id:
                decision_status.text = "Selecciona un juego y una variante."
                return
            state.overrides.setdefault(bucket, {})[selected_group["key"]] = rom_id  # type: ignore[union-attr]
            decision_status.text = f"Override {bucket} aplicado."
            refresh_decisions()

        def clear_override(bucket: str) -> None:
            if selected_group["key"]:
                state.overrides.setdefault(bucket, {}).pop(selected_group["key"], None)  # type: ignore[union-attr]
            decision_status.text = f"Override {bucket} eliminado."
            refresh_decisions()

        with ui.row():
            ui.button("Usar variante en main", icon="bookmark", on_click=lambda: set_override("main")).props("color=primary")
            ui.button("Usar variante en RA", icon="emoji_events", on_click=lambda: set_override("ra")).props("outline")
            ui.button("Quitar override main", icon="backspace", on_click=lambda: clear_override("main")).props("flat")
            ui.button("Quitar override RA", icon="backspace", on_click=lambda: clear_override("ra")).props("flat")

    ctx.refresh_decisions = refresh_decisions
