"""Pestaña Perfil: reglas 1G1R, presets recomendados y comparador de perfiles."""
from __future__ import annotations

from pathlib import Path

from nicegui import ui
from pydantic import ValidationError

from ..gui_context import UiContext
from ..gui_rows import (
    LANGUAGES,
    REGIONS,
    TAGS,
    _apply_profile_to_controls,
    _panel_class,
    _profile_from_controls,
    _profile_options,
)
from ..gui_state import _log_activity, _profile_comparison_rows, state
from ..models import ExportLayout
from ..profile import list_recommended_profiles, load_profile, save_named_profile


def build(ctx: UiContext) -> None:
    with ui.tab_panel(ctx.profile_tab).classes("p-0"):
        controls: dict[str, object] = {}
        with ui.column().classes(_panel_class()):
            ui.label("Perfil de selección").classes("text-lg font-semibold")
            with ui.row().classes("items-end gap-3"):
                profile_select = ui.select(_profile_options(), value="default", label="Cargar perfil").props("outlined").classes("w-80")
                controls["profile_name"] = ui.input("Nombre del perfil", value="custom").props("outlined").classes("w-80")
                controls["export_layout"] = ui.select(
                    {
                        ExportLayout.ORGANIZED.value: "Organizar por regiones y tipos",
                        ExportLayout.BUCKETS.value: "Salida clásica por main/RA",
                    },
                    value=ExportLayout.ORGANIZED.value,
                    label="Organización de salida",
                ).props("outlined").classes("w-80")
                controls["auto_patch_ra"] = ui.checkbox("Parchear automáticamente variantes RA cuando sea posible", value=False)
            with ui.row().classes("items-end gap-3"):
                recommended_profile = ui.select(
                    {name: name for name in list_recommended_profiles()},
                    value="1G1R + RA",
                    label="Perfil recomendado",
                ).props("outlined").classes("w-80")
                ui.label("Presets rápidos por objetivo; puedes cargarlos y luego ajustar reglas.").classes("text-sm text-gray-600")
            ui.label("Organizado: main se guarda en EUR/USA/JPN/etc.; RA solo añade variantes necesarias en Otros/RetroAchievements; hacks, prototypes, unlicensed y similares van a Otros.").classes("text-sm text-gray-600")
            ui.label("Auto-parche RA: descarga PatchUrl, aplica IPS/BPS y solo guarda la ROM si el MD5 final coincide con RetroAchievements. Otros formatos quedan bloqueados con aviso.").classes("text-sm text-gray-600")
            with ui.grid(columns=2).classes("w-full gap-4"):
                with ui.column().classes("border border-gray-200 rounded-md p-3"):
                    controls["main_enabled"] = ui.checkbox("Crear romset principal", value=True)
                    controls["main_strict_1g1r"] = ui.checkbox("1G1R estricto: solo DAT y una variante por juego", value=True)
                    controls["main_require_ra"] = ui.checkbox("Exigir compatibilidad RA", value=False)
                    controls["main_prefer_ra"] = ui.checkbox("Aceptar variante RA como main aunque no sea la última revisión", value=False)
                    controls["main_regions"] = ui.select(REGIONS, multiple=True, value=["Spain", "Europe", "World", "USA", "Japan"], label="Prioridad de regiones").props("outlined use-chips").classes("w-full")
                    controls["main_languages"] = ui.select(LANGUAGES, multiple=True, value=["Spanish", "English", "Multi"], label="Prioridad de idiomas").props("outlined use-chips").classes("w-full")
                    controls["main_tags"] = ui.select(TAGS, multiple=True, value=[], label="Excluir etiquetas").props("outlined use-chips").classes("w-full")
                    controls["main_newest"] = ui.checkbox("Preferir revisión más nueva", value=True)
                with ui.column().classes("border border-gray-200 rounded-md p-3"):
                    controls["ra_enabled"] = ui.checkbox("Crear romset RetroAchievements", value=True)
                    ui.label("RA siempre exige hash compatible.").classes("text-sm text-gray-600")
                    controls["ra_strict_1g1r"] = ui.checkbox("RA también exige DAT/1G1R estricto", value=False)
                    controls["ra_regions"] = ui.select(REGIONS, multiple=True, value=["Spain", "Europe", "World", "USA", "Japan"], label="Prioridad de regiones RA").props("outlined use-chips").classes("w-full")
                    controls["ra_languages"] = ui.select(LANGUAGES, multiple=True, value=["Spanish", "English", "Multi"], label="Prioridad de idiomas RA").props("outlined use-chips").classes("w-full")
                    controls["ra_tags"] = ui.select(TAGS, multiple=True, value=[], label="Excluir etiquetas RA").props("outlined use-chips").classes("w-full")
                    controls["ra_newest"] = ui.checkbox("Preferir revisión más nueva", value=True)
            profile_status = ui.label().classes("text-sm text-gray-600")

            def save_profile_click() -> None:
                try:
                    state.profile = _profile_from_controls(controls)
                    profile_status.text = "Perfil actualizado."
                except ValidationError as exc:
                    profile_status.text = f"Perfil inválido: {exc}"

            def persist_profile_click() -> None:
                try:
                    profile = _profile_from_controls(controls)
                    path = save_named_profile(profile)
                    state.profile = profile
                    profile_select.options = _profile_options()
                    profile_select.value = str(path)
                    profile_select.update()
                    profile_status.text = f"Perfil guardado: {path.name}"
                except Exception as exc:
                    profile_status.text = f"No se pudo guardar: {exc}"

            def load_profile_click() -> None:
                try:
                    selected = profile_select.value
                    profile = load_profile("default" if selected == "default" else Path(selected))
                    state.profile = profile
                    _apply_profile_to_controls(profile, controls)
                    profile_status.text = f"Perfil cargado: {profile.name}"
                except Exception as exc:
                    profile_status.text = f"No se pudo cargar: {exc}"

            def apply_recommended_profile_click() -> None:
                try:
                    profile = list_recommended_profiles()[recommended_profile.value]
                    state.profile = profile
                    _apply_profile_to_controls(profile, controls)
                    profile_status.text = f"Perfil recomendado cargado: {profile.name}"
                except Exception as exc:
                    profile_status.text = f"No se pudo cargar recomendación: {exc}"

            with ui.row():
                ui.button("Aplicar recomendado", icon="auto_awesome", on_click=apply_recommended_profile_click).props("color=primary")
                ui.button("Actualizar perfil", icon="check", on_click=save_profile_click).props("color=primary")
                ui.button("Guardar perfil", icon="save", on_click=persist_profile_click).props("outline")
                ui.button("Cargar perfil", icon="folder_open", on_click=load_profile_click).props("outline")
            ui.separator()
            ui.label("Comparador de perfiles").classes("text-md font-semibold")
            ui.label("Después de escanear, compara cuántos archivos guardaría cada preset antes de crear el plan definitivo.").classes("text-sm text-gray-600")
            profile_compare_table = ui.table(
                columns=[
                    {"name": "profile", "label": "Perfil", "field": "profile", "sortable": True, "align": "left"},
                    {"name": "main", "label": "Main", "field": "main", "sortable": True, "align": "right"},
                    {"name": "ra", "label": "RA", "field": "ra", "sortable": True, "align": "right"},
                    {"name": "total", "label": "Total", "field": "total", "sortable": True, "align": "right"},
                    {"name": "drops", "label": "Descartes", "field": "drops", "sortable": True, "align": "right"},
                    {"name": "note", "label": "Lectura rápida", "field": "note", "align": "left"},
                ],
                rows=[],
                pagination=8,
            ).props("dense flat bordered wrap-cells").classes("w-full compact-table")

            def compare_profiles_click() -> None:
                profile_compare_table.rows = _profile_comparison_rows(state.scan, ctx.outdir.value)
                profile_compare_table.update()
                if not profile_compare_table.rows:
                    profile_status.text = "Escanea primero para comparar perfiles."
                    return
                profile_status.text = "Comparación actualizada."
                _log_activity("Comparador de perfiles actualizado", "INFO")

            ui.button("Comparar presets con este escaneo", icon="compare", on_click=compare_profiles_click).props("outline")

    ctx.controls = controls
