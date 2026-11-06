"""Orquestación de la GUI: cabecera, control de acceso a pestañas y cambio de plataforma.

Las pestañas viven en gui_tabs/ (un módulo por pestaña), el estado global en
gui_state.py y los widgets compartidos en gui_widgets.py.
"""
from __future__ import annotations

from nicegui import app, ui

from .dat_sources import list_dat_sources
from .gui_context import UiContext
from .gui_rows import _dat_rows, _page_class, _ra_status_label
from .gui_shutdown import busy_reason, install_idle_shutdown, request_shutdown
from .gui_state import AppState, _current_platform, _log_activity, _online_dat_rows, reset_state, state
from .gui_tabs import activity, dats, decisions, download, plan, profile, scan, setup, summary, verify
from .gui_tabs import platform as platform_tab_module
from .gui_widgets import GLOBAL_CSS, _install_local_reconnect_guard
from .i18n import _, available_languages, set_language
from .models import Platform
from .platforms import platform_options, platform_spec
from .ra import ra_cache_count

__all__ = ["AppState", "build_ui", "reset_state", "run", "state"]


def build_ui() -> None:
    # Una pestaña nueva tiene que abrirse en el idioma ya elegido.
    set_language(state.language)
    _install_local_reconnect_guard()
    ui.colors(primary="#276a73", secondary="#8a5a44", accent="#46784f")
    dark_mode = ui.dark_mode(False)
    ui.add_css(GLOBAL_CSS)
    ctx = UiContext()

    with ui.header().classes("rp-header items-center bg-primary text-white px-4 py-2"):
        with ui.column().classes("gap-0 min-w-64"):
            ui.label(_("RetroPerfect")).classes("text-xl font-semibold")
            header_subtitle = ui.label().classes("text-sm opacity-80")
        with ui.row().classes("items-center gap-2 grow justify-center"):
            header_platform_icon_box = ui.element("div").classes("w-9 h-9 flex items-center justify-center")
            ctx.platform_select = ui.select(platform_options(), value=_current_platform().value, label=_("Plataforma")).props("outlined dense dark").classes("min-w-80")
        with ui.row().classes("items-center gap-2"):
            header_source_badge = ui.badge(_("Origen"), color="grey")
            header_dat_badge = ui.badge(_("DAT"), color="grey")
            header_ra_badge = ui.badge(_("RA"), color="grey")
            header_plan_badge = ui.badge(_("Plan"), color="grey")
            header_output_badge = ui.badge(_("Salida"), color="grey")
            ui.badge(_("Local"), color="secondary")
            theme_button = ui.button(_("Oscuro"), icon="dark_mode").props("dense unelevated color=white text-color=primary")

            def toggle_theme() -> None:
                enabled = not bool(state.dark_mode)
                state.dark_mode = enabled
                dark_mode.set_value(enabled)
                theme_button.text = "Claro" if enabled else "Oscuro"
                theme_button.props(f"icon={'light_mode' if enabled else 'dark_mode'}")
                theme_button.update()

            theme_button.on_click(toggle_theme)

            # La interfaz se construye una sola vez por página, así que cambiar
            # de idioma recarga: traducir en caliente cada widget ya creado
            # sería mucho más código para el mismo resultado.
            def switch_language(code: str) -> None:
                if code == state.language:
                    return
                state.language = set_language(code)
                ui.navigate.reload()

            ui.select(
                available_languages(),
                value=state.language,
                label=_("Idioma"),
                on_change=lambda event: switch_language(event.value),
            ).props("outlined dense dark").classes("w-36")

            quit_dialog = ui.dialog()
            with quit_dialog, ui.card().classes("w-[460px] max-w-[95vw]"):
                ui.label(_("Cerrar RetroPerfect")).classes("text-lg font-semibold")
                quit_message = ui.label().classes("text-sm text-gray-700")
                with ui.row().classes("justify-end w-full"):
                    ui.button(_("Cancelar"), icon="close", on_click=quit_dialog.close).props("flat")

                    async def confirm_quit() -> None:
                        quit_dialog.close()
                        _log_activity("Cierre solicitado desde la interfaz", "INFO")
                        await request_shutdown()

                    ui.button(_("Cerrar"), icon="power_settings_new", on_click=confirm_quit).props("color=negative")

            def quit_click() -> None:
                reason = busy_reason()
                quit_message.text = (
                    f"Hay una operación en curso ({reason}). Si cierras ahora quedará a medias. ¿Cerrar de todas formas?"
                    if reason
                    else "Se detendrá el servidor local y esta pestaña dejará de funcionar. Tu trabajo guardado no se pierde."
                )
                quit_dialog.open()

            ui.button(_("Salir"), icon="power_settings_new", on_click=quit_click).props("dense unelevated color=negative")

    with ui.column().classes(_page_class()):
        with ui.tabs().classes("w-full") as tabs:
            ctx.platform_tab = ui.tab(_("Plataforma"), icon="category")
            ctx.setup_tab = ui.tab(_("Setup"), icon="settings")
            ctx.dats_tab = ui.tab(_("Biblioteca DAT"), icon="inventory_2")
            ctx.profile_tab = ui.tab(_("Perfil"), icon="tune")
            ctx.scan_tab = ui.tab(_("Escaneo"), icon="search")
            ctx.verify_tab = ui.tab(_("Verificar"), icon="verified")
            ctx.download_tab = ui.tab(_("Descargar"), icon="cloud_download")
            ctx.decisions_tab = ui.tab(_("Decisiones"), icon="fact_check")
            ctx.plan_tab = ui.tab(_("Plan"), icon="rule")
            ctx.summary_tab = ui.tab(_("Resumen"), icon="dashboard")
            ctx.activity_tab = ui.tab(_("Actividad"), icon="history")

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
            _set_tab_enabled(ctx.verify_tab, setup_ready and has_scan)
            # Descargar no se bloquea: las fuentes se configuran antes de tener nada
            # escaneado, y el propio botón de plan avisa si falta el DAT o el origen.
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
            verify.build(ctx)
            download.build(ctx)
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
            ctx.scan_status.text = _("La plataforma ha cambiado. Valida el setup y escanea de nuevo.")
            ctx.refresh_coverage()
            ctx.refresh_decisions()
            update_tab_access()
            refresh_header_status()

        # El hook se conecta cuando todas las pestañas ya registraron sus refs.
        ctx.platform_select.on_value_change(lambda event: switch_platform(event.value))


# Direcciones que solo alcanza esta máquina. Cualquier otra publica la interfaz
# en la red.
LOOPBACK_HOSTS = {"", "127.0.0.1", "::1", "localhost", "127.0.0.0/8"}


def assert_host_is_safe(host: str, allow_remote: bool = False) -> None:
    """Comprueba que la interfaz no se publique en la red sin querer.

    No hay usuarios ni contraseñas: quien alcance el puerto puede explorar todo
    el disco con el selector de archivos, planificar y borrar. Eso está bien
    mientras solo escuche en loopback, pero `--host 0.0.0.0` lo dejaba al
    alcance de toda la red local sin un solo aviso.
    """
    if host in LOOPBACK_HOSTS or allow_remote:
        return
    raise RuntimeError(
        f"Escuchar en {host} publica la interfaz en la red, y RetroPerfect no pide ninguna credencial: "
        "quien llegue al puerto puede explorar tus carpetas y borrar archivos. "
        "Si es lo que quieres (una red en la que confías, un contenedor), repite con --allow-remote."
    )


def run(host: str = "127.0.0.1", port: int = 8080, show: bool = False, exit_on_idle: bool = False, allow_remote: bool = False) -> None:
    """Arranca la interfaz local.

    `show` abre el navegador automáticamente y `exit_on_idle` cierra la aplicación
    cuando no queda ningún navegador conectado: los usa la app empaquetada, que no
    tiene terminal ni icono en el Dock donde ver la URL o terminar el proceso.
    """
    assert_host_is_safe(host, allow_remote)
    app.config.socket_io_js_transports = ["polling", "websocket"]
    if exit_on_idle:
        install_idle_shutdown()
    ui.run(
        build_ui,
        host=host,
        port=port,
        title=_("RetroPerfect"),
        reload=False,
        show=show,
        reconnect_timeout=30.0,
        message_history_length=5000,
        uvicorn_logging_level="info",
        timeout_keep_alive=30,
    )


if __name__ in {"__main__", "__mp_main__"}:
    run()
