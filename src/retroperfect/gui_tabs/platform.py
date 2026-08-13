"""Pestaña Plataforma: catálogo de sistemas y tabla de requisitos."""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from ..diagnostics import build_needed_rows
from ..gui_context import UiContext
from ..gui_rows import (
    _diagnostic_rows,
    _panel_class,
    _platform_card_rows_for_tab,
)
from ..gui_state import _current_platform, state
from ..platforms import list_platforms, platform_spec


def build(ctx: UiContext) -> None:
    with ui.tab_panel(ctx.platform_tab).classes("p-0"), ui.column().classes(_panel_class() + " mb-4"):
        ui.label("Plataforma").classes("text-lg font-semibold")
        platform_status = ui.label().classes("text-sm text-gray-600")
        kinds = ["Todos", *sorted({spec.kind for spec in list_platforms()})]
        generations = ["Todas", *sorted({spec.generation for spec in list_platforms()})]
        platform_family = {"value": "Todas"}
        with ui.tabs().classes("w-full rp-platform-tabs").props("breakpoint=0") as platform_tabs:
            for tab_label in ["Todas", "Nintendo", "Sega", "Atari", "NEC", "Sony", "Microsoft", "Arcade", "SNK/Bandai", "Apple", "Commodore", "Discos/Digital", "Ordenadores", "Otras", "Especiales"]:
                ui.tab(tab_label)
        platform_tabs.value = "Todas"
        with ui.row().classes("w-full gap-3 items-end"):
            platform_search = ui.input("Buscar plataforma").props("outlined dense clearable").classes("w-64")
            kind_filter = ui.select(kinds, value="Todos", label="Tipo").props("outlined dense").classes("w-48")
            generation_filter = ui.select(generations, value="Todas", label="Generación").props("outlined dense").classes("w-48")
            ui.space()
            ui.label("Elige una consola; DAT, RA, extensiones y escaneo se adaptan a ella. Especiales incluye sistemas experimentales u ordenadores de cartucho.").classes("text-sm text-gray-500")
        platform_cards = ui.element("div").classes("rp-platform-strip")

        def refresh_platform_cards() -> None:
            platform_cards.clear()
            with platform_cards:
                rows = _platform_card_rows_for_tab(platform_family["value"], kind_filter.value, generation_filter.value, platform_search.value or "")
                if not rows:
                    ui.label("No hay plataformas en este filtro.").classes("text-sm text-gray-500")
                    return
                for row in rows:
                    active_class = " rp-platform-card-active" if row["id"] == _current_platform().value else ""
                    with ui.element("div").classes(f"rp-platform-card{active_class}").on("click", lambda _, value=row["id"]: ctx.platform_select.set_value(value)):
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            if row["icon_url"]:
                                ui.image(row["icon_url"]).classes("rp-platform-icon")
                            else:
                                ui.icon(row["icon"]).classes("text-3xl text-primary")
                            with ui.column().classes("gap-0 min-w-0"):
                                ui.label(row["name"]).classes("font-semibold text-sm")
                                ui.label(row["brand"]).classes("text-xs text-gray-500")
                        with ui.row().classes("items-center gap-1 mt-2"):
                            ui.badge(row["ra"], color="green" if row["ra"] == "RA" else ("blue-grey" if row["ra"] == "RA inactivo" else "grey"))
                            ui.badge(row["complexity"], color="amber" if row["complexity"] != "simple" else "blue-grey")
                        with ui.element("div").classes("rp-platform-field mt-2"):
                            ui.html("<span>Tipo</span>")
                            ui.html(f"<span>{row['generation']} · {row['kind']}</span>")
                            ui.html("<span>Ext.</span>")
                            ui.html(f"<span>{row['extensions']}</span>")
                            ui.html("<span>DAT</span>")
                            ui.html(f"<span>{row['dat']}</span>")
                        ui.label(row["tip"]).classes("text-xs text-gray-500 mt-2")

        def refresh_platform_status() -> None:
            spec = platform_spec(_current_platform())
            platform_status.text = f"Activa: {spec.short_name}. Extensiones: {spec.extension_label}. DAT: {spec.dat_recommended}. Romset: {spec.romset_recommended}"
            refresh_platform_cards()

        def platform_tab_change(event) -> None:
            platform_family["value"] = event.value or "Todas"
            refresh_platform_cards()

        platform_tabs.on_value_change(platform_tab_change)
        platform_search.on_value_change(lambda _: refresh_platform_cards())
        kind_filter.on_value_change(lambda _: refresh_platform_cards())
        generation_filter.on_value_change(lambda _: refresh_platform_cards())
        refresh_platform_status()
        ui.separator()
        ui.label("Qué necesito descargar/importar").classes("text-md font-semibold")
        needed_table = ui.table(
            columns=[
                {"name": "status", "label": "", "field": "status", "align": "center"},
                {"name": "item", "label": "Elemento", "field": "item", "sortable": True, "align": "left"},
                {"name": "detail", "label": "Detalle", "field": "detail", "align": "left"},
                {"name": "recommendation", "label": "Recomendación", "field": "recommendation", "align": "left"},
            ],
            rows=[],
            pagination=6,
        ).props("dense flat bordered wrap-cells").classes("w-full compact-table")
        needed_table.add_slot(
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

        def refresh_needed_table() -> None:
            needed_table.rows = _diagnostic_rows(
                build_needed_rows(
                    _current_platform(),
                    Path(ctx.source.value) if ctx.source is not None and ctx.source.value else None,
                    Path(ctx.dat.value) if ctx.dat is not None and ctx.dat.value else None,
                    state.scan,  # type: ignore[arg-type]
                )
            )
            needed_table.update()

        refresh_needed_table()

    ctx.platform_status = platform_status
    ctx.refresh_platform_cards = refresh_platform_cards
    ctx.refresh_needed_table = refresh_needed_table
