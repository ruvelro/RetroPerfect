"""Orquestación de la GUI: cabecera, control de acceso a pestañas y cambio de plataforma.

Las pestañas viven en gui_tabs/ (un módulo por pestaña), el estado global en
gui_state.py y los widgets compartidos en gui_widgets.py.
"""
from __future__ import annotations

from nicegui import app, ui

from .dat_sources import list_dat_sources
from .gui_context import UiContext
from .gui_rows import _dat_rows, _page_class, _ra_status_label
from .gui_state import AppState, _current_platform, _online_dat_rows, reset_state, state
from .gui_tabs import activity, dats, decisions, plan, profile, scan, setup, summary
from .gui_tabs import platform as platform_tab_module
from .gui_widgets import GLOBAL_CSS, _install_local_reconnect_guard
from .models import Platform
from .platforms import platform_options, platform_spec
from .ra import ra_cache_count

__all__ = ["AppState", "build_ui", "reset_state", "run", "state"]


def build_ui() -> None:
    _install_local_reconnect_guard()
    ui.colors(primary="#276a73", secondary="#8a5a44", accent="#46784f")
    dark_mode = ui.dark_mode(False)
    ui.add_css(GLOBAL_CSS)
    ctx = UiContext()

    with ui.header().classes("rp-header items-center bg-primary text-white px-4 py-2"):
        with ui.column().classes("gap-0 min-w-64"):
            ui.label("RetroPerfect").classes("text-xl font-semibold")
            header_subtitle = ui.label().classes("text-sm opacity-80")
        with ui.row().classes("items-center gap-2 grow justify-center"):
            header_platform_icon_box = ui.element("div").classes("w-9 h-9 flex items-center justify-center")
            ctx.platform_select = ui.select(platform_options(), value=_current_platform().value, label="Plataforma").props("outlined dense dark").classes("min-w-80")
        with ui.row().classes("items-center gap-2"):
            header_source_badge = ui.badge("Origen", color="grey")
            header_dat_badge = ui.badge("DAT", color="grey")
            header_ra_badge = ui.badge("RA", color="grey")
            header_plan_badge = ui.badge("Plan", color="grey")
            header_output_badge = ui.badge("Salida", color="grey")
            ui.badge("Local", color="secondary")
            theme_button = ui.button("Oscuro", icon="dark_mode").props("dense flat").classes("rp-theme-button")

            def toggle_theme() -> None:
                enabled = not bool(state.dark_mode)
                state.dark_mode = enabled
                dark_mode.set_value(enabled)
                theme_button.text = "Claro" if enabled else "Oscuro"
                theme_button.props(f"icon={'light_mode' if enabled else 'dark_mode'}")
                theme_button.update()

            theme_button.on_click(toggle_theme)

    with ui.column().classes(_page_class()):
        with ui.tabs().classes("w-full") as tabs:
            ctx.platform_tab = ui.tab("Plataforma", icon="category")
            ctx.setup_tab = ui.tab("Setup", icon="settings")
            ctx.dats_tab = ui.tab("Biblioteca DAT", icon="inventory_2")
            ctx.profile_tab = ui.tab("Perfil", icon="tune")
            ctx.scan_tab = ui.tab("Escaneo", icon="search")
            ctx.decisions_tab = ui.tab("Decisiones", icon="fact_check")
            ctx.plan_tab = ui.tab("Plan", icon="rule")
            ctx.summary_tab = ui.tab("Resumen", icon="dashboard")
            ctx.activity_tab = ui.tab("Actividad", icon="history")

        def has_control_value(name: str) -> bool:
            control = ctx.header_refs.get(name)
            return bool(getattr(control, "value", None))

        def refresh_header_status() -> None:
            spec = platform_spec(_current_platform())
            header_subtitle.text = f"{spec.short_name} · {spec.brand} · {spec.generation} · {spec.dat_recommended}"
            header_platform_icon_box.clear()
            with header_platform_icon_box:
                if spec.icon_url:
                    ui.image(spec.icon_url).classes("rp-platform-icon")
                else:
                    ui.icon(spec.icon).classes("text-3xl")
            header_source_badge.props(f"color={'green' if has_control_value('source') else 'grey'}")
            header_dat_badge.props(f"color={'green' if has_control_value('dat') else 'grey'}")
            header_ra_badge.text = "RA" if spec.ra_active else spec.ra_label
            header_ra_badge.props(f"color={'green' if ra_cache_count(_current_platform()) else ('blue-grey' if spec.supports_ra else 'grey')}")
            header_plan_badge.props(f"color={'green' if state.manifest else 'grey'}")
            header_output_badge.props(f"color={'green' if has_control_value('outdir') else 'grey'}")

        def _set_tab_enabled(tab, enabled: bool) -> None:
            if enabled:
                tab.props(remove="disable")
                tab.classes(remove="opacity-50")
            else:
                tab.props("disable")
                tab.classes("opacity-50")

        def update_tab_access() -> None:
            setup_ready = bool(state.setup_ready)
            has_scan = state.scan is not None
            has_manifest = state.manifest is not None
            _set_tab_enabled(ctx.profile_tab, setup_ready)
            _set_tab_enabled(ctx.scan_tab, setup_ready)
            _set_tab_enabled(ctx.decisions_tab, setup_ready and has_scan)
            _set_tab_enabled(ctx.plan_tab, setup_ready and has_scan)
            _set_tab_enabled(ctx.summary_tab, setup_ready and has_scan and has_manifest)

        def set_setup_ready(ready: bool) -> None:
            state.setup_ready = ready
            update_tab_access()
            refresh_header_status()

        def mark_setup_dirty() -> None:
            if state.suppress_setup_dirty:
                return
            if state.setup_ready:
                set_setup_ready(False)
            refresh_header_status()

        ctx.refresh_header_status = refresh_header_status
        ctx.update_tab_access = update_tab_access
        ctx.set_setup_ready = set_setup_ready
        ctx.mark_setup_dirty = mark_setup_dirty

        set_setup_ready(False)

        with ui.tab_panels(tabs, value=ctx.platform_tab).classes("w-full bg-transparent"):
            platform_tab_module.build(ctx)
            setup.build(ctx)
            dats.build(ctx)
            profile.build(ctx)
            scan.build(ctx)
            summary.build(ctx)
            decisions.build(ctx)
            plan.build(ctx)
            activity.build(ctx)

        def switch_platform(value: str) -> None:
            new_platform = Platform(value)
            if new_platform == _current_platform():
                return
            state.platform = new_platform
            state.scan = None
            state.manifest = None
            state.catalog = None
            state.coverage = None
            state.overrides = {"main": {}, "ra": {}}
            mark_setup_dirty()
            spec = platform_spec(new_platform)
            ctx.dat_source.options = {item.id: item.label for item in list_dat_sources(new_platform.value)}
            ctx.dat_source.value = next(iter(ctx.dat_source.options), None)
            ctx.dat_source.update()
            ctx.online_table.rows = _online_dat_rows(new_platform)
            ctx.online_table.update()
            ctx.dat_table.rows = _dat_rows(new_platform)
            ctx.dat_table.update()
            ctx.platform_status.text = f"Activa: {spec.short_name}. Extensiones: {spec.extension_label}. DAT: {spec.dat_recommended}. Romset: {spec.romset_recommended}"
            ctx.refresh_platform_cards()
            ctx.refresh_setup_platform_summary()
            ctx.refresh_needed_table()
            ctx.ra_cache_status.text = _ra_status_label(new_platform)
            ctx.scan_status.text = "La plataforma ha cambiado. Valida el setup y escanea de nuevo."
            ctx.refresh_coverage()
            ctx.refresh_decisions()
            update_tab_access()
            refresh_header_status()

        # El hook se conecta cuando todas las pestañas ya registraron sus refs.
        ctx.platform_select.on_value_change(lambda event: switch_platform(event.value))


def run(host: str = "127.0.0.1", port: int = 8080) -> None:
    app.config.socket_io_js_transports = ["polling", "websocket"]
    ui.run(
        build_ui,
        host=host,
        port=port,
        title="RetroPerfect",
        reload=False,
        show=False,
        reconnect_timeout=30.0,
        message_history_length=5000,
        uvicorn_logging_level="info",
        timeout_keep_alive=30,
    )


if __name__ in {"__main__", "__mp_main__"}:
    run()
