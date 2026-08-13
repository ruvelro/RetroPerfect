from __future__ import annotations

import asyncio
import json
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import cast

from nicegui import app, ui
from pydantic import ValidationError

from .coverage import build_coverage
from .dat import DatIndex, parse_dat
from .dat_manager import compare_dats, download_and_import_source, download_and_import_url, import_dat_file, suggest_dat_for_source, validate_setup
from .dat_sources import DAT_SOURCES, list_dat_sources
from .diagnostics import build_needed_rows, build_perfect_audit, detect_dat_warnings
from .gui_rows import (
    ACTION_LABELS,
    DATOMATIC_GAP_ROWS,
    LANGUAGES,
    REGIONS,
    TAGS,
    _apply_profile_to_controls,
    _bucket_divergence_rows,
    _coverage_rows,
    _coverage_variant_rows,
    _dat_rows,
    _decision_detail,
    _diagnostic_rows,
    _direct_dat_batch_candidates,
    _duplicate_rows,
    _export_tree_rows,
    _flag_regions,
    _latest_project_path,
    _page_class,
    _panel_class,
    _patch_queue_rows,
    _plan_reason_icons,
    _platform_card_rows_for_tab,
    _profile_from_controls,
    _profile_options,
    _ra_conflict_rows,
    _ra_icon,
    _ra_status_label,
    _rom_summary_key,
    _scan_group_sample,
    _source_suffixes,
    _unmatched_rows,
)
from .manifest_io import apply_manifest, preflight_manifest, report_manifest, save_manifest
from .models import ActionMode, ExportLayout, OutputBucket, Platform, ProfileOutput, SelectionProfile
from .paths import project_state_dir
from .platforms import list_platforms, platform_options, platform_spec
from .profile import DEFAULT_PROFILE, list_recommended_profiles, load_profile, save_named_profile
from .ra import annotate_scan_with_ra, credentials_path, ra_cache_count, ra_sync_status, save_credentials, sync_ra_hashes, sync_ra_patch_details
from .rules import build_manifest, explain_score
from .scanner import scan_directory
from .storage import save_scan

# Estado global de la aplicación: RetroPerfect es una herramienta local
# mono-usuario; todas las pestañas del navegador comparten este estado.
state: dict[str, object] = {
    "platform": Platform.NES,
    "scan": None,
    "manifest": None,
    "profile": DEFAULT_PROFILE.model_copy(deep=True),
    "catalog": None,
    "coverage": None,
    "overrides": {"main": {}, "ra": {}},
    "setup_ready": False,
    "suppress_setup_dirty": False,
    "scan_progress": {"current": 0, "total": 0, "path": "", "roms": 0, "matched": 0, "phase": "idle"},
    "ra_details_progress": {"current": 0, "total": 0, "updated": 0, "running": False},
    "dark_mode": False,
    "activity": [],
}


def _current_platform() -> Platform:
    return Platform(state.get("platform", Platform.NES))


def _small_button(label: str, icon: str, on_click) -> ui.button:
    return ui.button(label, icon=icon, on_click=on_click).props("dense outline")


def _log_activity(message: str, level: str = "INFO") -> None:
    rows = list(cast(list[dict[str, str]], state.get("activity") or []))
    rows.insert(
        0,
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        },
    )
    state["activity"] = rows[:200]


def _activity_rows() -> list[dict[str, str]]:
    return list(cast(list[dict[str, str]], state.get("activity") or []))


def _open_path(path: Path | str | None) -> None:
    if not path:
        return
    target = Path(path).expanduser()
    if target.exists():
        webbrowser.open(target.resolve().as_uri())


def _profile_comparison_rows(scan, output_dir: str | None) -> list[dict[str, str | int]]:
    if scan is None:
        return []
    rows: list[dict[str, str | int]] = []
    for name, profile in list_recommended_profiles().items():
        try:
            manifest = build_manifest(
                scan,
                profile,
                [output.bucket for output in profile.outputs],
                output_dir=Path(output_dir) if output_dir else None,
                action=ActionMode.COPY,
                overrides=state["overrides"],  # type: ignore[arg-type]
            )
        except Exception as exc:
            rows.append({"profile": name, "main": 0, "ra": 0, "total": 0, "drops": 0, "note": f"Error: {exc}"})
            continue
        main = sum(1 for entry in manifest.entries if entry.bucket == OutputBucket.MAIN)
        ra = sum(1 for entry in manifest.entries if entry.bucket == OutputBucket.RA)
        drops = sum(1 for decision in manifest.discarded if not decision.kept)
        rows.append(
            {
                "profile": name,
                "main": main,
                "ra": ra,
                "total": len(manifest.entries),
                "drops": drops,
                "note": "RA añade variantes extra" if ra and ra != main else "main cubre el objetivo",
            }
        )
    return rows


def _install_local_reconnect_guard() -> None:
    ui.add_body_html(
        """
        <script>
        (() => {
          if (window.__retroperfectReconnectGuard) return;
          window.__retroperfectReconnectGuard = true;

          const reconnectAfterMs = 7000;
          let reloadTimer = null;

          const hidePopup = () => {
            const popup = document.getElementById('popup');
            if (popup) popup.setAttribute('aria-hidden', 'true');
          };

          const scheduleReload = () => {
            hidePopup();
            if (reloadTimer !== null) return;
            reloadTimer = window.setTimeout(async () => {
              try {
                const response = await fetch(window.location.href, {
                  method: 'HEAD',
                  cache: 'no-store',
                });
                if (!response.ok) throw new Error('local server not ready');
              } catch (_) {
                reloadTimer = null;
                scheduleReload();
                return;
              }
              window.location.reload();
            }, reconnectAfterMs);
          };

          const clearReload = () => {
            if (reloadTimer !== null) {
              window.clearTimeout(reloadTimer);
              reloadTimer = null;
            }
            hidePopup();
          };

          const attach = () => {
            if (!window.socket || window.socket.__retroperfectGuardAttached) return false;
            window.socket.__retroperfectGuardAttached = true;
            window.socket.on('disconnect', scheduleReload);
            window.socket.on('connect', clearReload);
            window.socket.io?.on('reconnect', clearReload);
            window.socket.io?.on('reconnect_failed', scheduleReload);
            return true;
          };

          const interval = window.setInterval(() => {
            if (attach()) window.clearInterval(interval);
          }, 250);

          window.addEventListener('online', () => {
            if (reloadTimer !== null) window.location.reload();
          });
        })();
        </script>
        """
    )


def _path_picker(target: ui.input, *, choose: str, suffixes: set[str] | None = None) -> ui.dialog:
    dialog = ui.dialog()
    current = {"path": Path.cwd()}
    suffixes = suffixes or set()

    def allowed(path: Path) -> bool:
        return choose == "directory" or not suffixes or path.suffix.lower() in suffixes

    with dialog, ui.card().classes("w-[900px] max-w-[95vw]"):
        ui.label("Explorar archivos").classes("text-lg font-semibold")
        path_label = ui.label().classes("text-sm text-gray-600")
        entries = ui.column().classes("w-full max-h-[55vh] overflow-auto border border-gray-200 rounded-md p-2 gap-1")

        def refresh(path: Path) -> None:
            resolved = path.expanduser()
            if resolved.is_file():
                resolved = resolved.parent
            if not resolved.exists():
                resolved = Path.cwd()
            current["path"] = resolved
            path_label.text = str(resolved)
            entries.clear()
            with entries:
                if resolved.parent != resolved:
                    ui.button("..", icon="drive_folder_upload", on_click=lambda: refresh(resolved.parent)).props("flat dense").classes("justify-start w-full")
                for child in sorted(resolved.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
                    if child.name.startswith("."):
                        continue
                    if child.is_dir():
                        ui.button(child.name, icon="folder", on_click=lambda child=child: refresh(child)).props("flat dense").classes("justify-start w-full")
                    elif allowed(child):
                        ui.button(child.name, icon="description", on_click=lambda child=child: select(child)).props("flat dense").classes("justify-start w-full")

        def select(path: Path) -> None:
            target.value = str(path)
            dialog.close()

        with ui.row().classes("w-full items-center"):
            _small_button("Inicio", "home", lambda: refresh(Path.home()))
            _small_button("Proyecto", "terminal", lambda: refresh(Path.cwd()))
            ui.space()
            if choose in {"directory", "any"}:
                ui.button("Usar esta carpeta", icon="check", on_click=lambda: select(current["path"])).props("color=primary")
            ui.button("Cerrar", icon="close", on_click=dialog.close).props("flat")
        refresh(Path.cwd())
    return dialog


def _group_rows(scan) -> list[dict[str, str | int]]:
    if scan is None:
        return []
    grouped: dict[str, list] = {}
    for rom in scan.roms:
        grouped.setdefault(_rom_summary_key(rom), []).append(rom)
    rows = []
    overrides = state["overrides"]
    for key, roms in sorted(grouped.items(), key=lambda item: item[0].lower()):
        main_id = overrides.get("main", {}).get(key)  # type: ignore[union-attr]
        ra_id = overrides.get("ra", {}).get(key)  # type: ignore[union-attr]
        main_rom = next((rom for rom in roms if rom.id == main_id), None)
        ra_rom = next((rom for rom in roms if rom.id == ra_id), None)
        rows.append(
            {
                "group": key,
                "title": roms[0].metadata.title,
                "variants": len(roms),
                "regions": _flag_regions(sorted({region for rom in roms for region in rom.metadata.regions})),
                "ra": "🏆 🩹" if any(rom.ra_patch_url or "rapatches" in {label.lower() for label in rom.ra_labels} for rom in roms) else ("🏆" if any(rom.ra_game_id for rom in roms) else ""),
                "main_override": Path(main_rom.container_path).name if main_rom else "",
                "ra_override": Path(ra_rom.container_path).name if ra_rom else "",
            }
        )
    return rows


def _variant_rows(scan, group_key: str, profile: SelectionProfile) -> list[dict[str, str]]:
    if scan is None or not group_key:
        return []
    roms = [rom for rom in scan.roms if _rom_summary_key(rom) == group_key]
    main_output = next((output for output in profile.outputs if output.bucket == OutputBucket.MAIN), ProfileOutput(bucket=OutputBucket.MAIN))
    main_override = state["overrides"].get("main", {}).get(group_key)  # type: ignore[union-attr]
    ra_override = state["overrides"].get("ra", {}).get(group_key)  # type: ignore[union-attr]
    return [
        {
            "id": rom.id,
            "choice": ", ".join(bucket for bucket, selected in [("main", rom.id == main_override), ("RA", rom.id == ra_override)] if selected),
            "dat": "✅" if rom.dat_game else "❌",
            "file": Path(rom.container_path).name if not rom.inner_path else f"{Path(rom.container_path).name} / {rom.inner_path}",
            "regions": _flag_regions(rom.metadata.regions),
            "languages": ", ".join(rom.metadata.languages),
            "revision": rom.metadata.version or str(rom.metadata.revision or ""),
            "ra": _ra_icon(rom),
            "tags": ", ".join(rom.metadata.tags),
            "priority": _decision_detail(explain_score(rom, main_output), fallback="ℹ️"),
            "score": " | ".join(explain_score(rom, main_output)),
        }
        for rom in roms
    ]


def _online_dat_rows(platform: Platform | None = None) -> list[dict[str, str]]:
    platform = platform or _current_platform()
    return [
        {
            "id": source.id,
            "label": source.label,
            "format": source.format,
            "direct": "sí" if source.direct_download else "no",
            "url": source.url,
            "notes": source.notes,
        }
        for source in list_dat_sources(platform.value)
    ]


def build_ui() -> None:
    _install_local_reconnect_guard()
    ui.colors(primary="#276a73", secondary="#8a5a44", accent="#46784f")
    dark_mode = ui.dark_mode(False)
    ui.add_css(
        """
        body { background: #f6f7f8; color: #172326; }
        body.body--dark { background: #101719; color: #e8eef0; }
        .q-tab-panel, .q-panel, .nicegui-content { background: transparent; }
        .nicegui-content { padding: 0; }
        #popup.nicegui-error-popup {
            display: none !important;
        }
        .q-table th, .q-table td {
            text-align: left !important;
            white-space: normal !important;
            overflow-wrap: anywhere;
            line-height: 1.25rem;
            vertical-align: top;
        }
        .q-table__container {
            max-width: 100%;
        }
        .q-table__middle {
            overflow-x: hidden;
        }
        .compact-table .q-table th,
        .compact-table .q-table td {
            padding: 6px 8px;
            font-size: 12px;
        }
        .q-table th.text-center, .q-table td.text-center {
            text-align: center !important;
        }
        .q-table th.text-right, .q-table td.text-right {
            text-align: right !important;
        }
        .rp-center, .rp-center * {
            text-align: center !important;
        }
        .rp-right, .rp-right * {
            text-align: right !important;
        }
        .rp-table-card {
            width: 100%;
            min-height: 260px;
        }
        .rp-header {
            min-height: 76px;
            gap: 16px;
            flex-wrap: wrap;
        }
        .rp-platform-strip {
            width: 100%;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
            gap: 10px;
        }
        .rp-platform-tabs .q-tabs__content {
            flex-wrap: wrap;
            row-gap: 4px;
        }
        .rp-platform-tabs .q-tabs__content--align-center {
            justify-content: flex-start;
        }
        .rp-platform-tabs .q-tab {
            min-height: 36px;
            padding: 0 10px;
        }
        .rp-platform-card {
            border: 1px solid #d8e1e4;
            border-radius: 8px;
            padding: 10px;
            background: #fff;
            cursor: pointer;
            min-height: 156px;
        }
        .rp-platform-card:hover {
            border-color: #276a73;
            box-shadow: 0 2px 8px rgba(22, 79, 86, 0.12);
        }
        .rp-platform-card-active {
            border-color: #276a73;
            background: #eef7f8;
        }
        .rp-platform-icon {
            width: 34px;
            height: 34px;
            object-fit: contain;
            image-rendering: auto;
        }
        .rp-platform-field {
            display: grid;
            grid-template-columns: 52px 1fr;
            gap: 6px;
            font-size: 11px;
            line-height: 1.18rem;
        }
        .rp-platform-field span:first-child {
            color: #667085;
        }
        .rp-panel {
            background: #fff;
        }
        .rp-step-card {
            background: #fff;
        }
        .rp-theme-button {
            border: 1px solid rgba(255,255,255,.45);
            color: #fff !important;
            background: rgba(255,255,255,.10) !important;
        }
        body.body--dark .bg-white,
        body.body--dark .rp-panel,
        body.body--dark .rp-step-card,
        body.body--dark .rp-platform-card,
        body.body--dark .q-tab-panel,
        body.body--dark .q-panel,
        body.body--dark .q-page,
        body.body--dark .nicegui-content,
        body.body--dark .q-table__container,
        body.body--dark .q-card {
            background: #172326 !important;
            color: #e8eef0 !important;
            border-color: #34494f !important;
        }
        body.body--dark .q-layout,
        body.body--dark .q-page-container {
            background: #101719 !important;
        }
        body.body--dark .rp-platform-card-active {
            background: #203a40 !important;
            border-color: #5bb8c4 !important;
        }
        body.body--dark .rp-platform-tabs .q-tab,
        body.body--dark .q-tabs {
            color: #c9d6da !important;
            background: transparent !important;
        }
        body.body--dark .rp-platform-tabs .q-tab--active {
            color: #ffffff !important;
        }
        body.body--dark .text-gray-500,
        body.body--dark .text-gray-600,
        body.body--dark .text-gray-700 {
            color: #a8bac0 !important;
        }
        body.body--dark .border-gray-200 {
            border-color: #34494f !important;
        }
        body.body--dark .q-table th {
            background: #203036 !important;
            color: #e8eef0 !important;
        }
        body.body--dark .q-table td {
            color: #e8eef0 !important;
            border-color: #34494f !important;
        }
        body.body--dark .q-field__control,
        body.body--dark .q-field__native,
        body.body--dark .q-field__label,
        body.body--dark .q-field__append,
        body.body--dark .q-menu,
        body.body--dark .q-list {
            background: #172326 !important;
            color: #e8eef0 !important;
        }
        body.body--dark .q-field--outlined .q-field__control:before {
            border-color: #60777e !important;
        }
        body.body--dark .q-field--outlined .q-field__control:hover:before {
            border-color: #8fb2bb !important;
        }
        body.body--dark .q-badge {
            color: #fff;
        }
        """
    )
    summary_actions: dict[str, object] = {}

    async def run_summary_plan_click() -> None:
        action = summary_actions.get("plan")
        if action is None:
            ui.notify("El plan aun no esta listo en la interfaz.", color="warning")
            return
        await action()  # type: ignore[misc]

    async def run_summary_apply_click() -> None:
        action = summary_actions.get("apply")
        if action is None:
            ui.notify("El aplicador aun no esta listo en la interfaz.", color="warning")
            return
        await action()  # type: ignore[misc]

    with ui.header().classes("rp-header items-center bg-primary text-white px-4 py-2"):
        with ui.column().classes("gap-0 min-w-64"):
            ui.label("RetroPerfect").classes("text-xl font-semibold")
            header_subtitle = ui.label().classes("text-sm opacity-80")
        with ui.row().classes("items-center gap-2 grow justify-center"):
            header_platform_icon_box = ui.element("div").classes("w-9 h-9 flex items-center justify-center")
            platform_select = ui.select(platform_options(), value=_current_platform().value, label="Plataforma").props("outlined dense dark").classes("min-w-80")
        with ui.row().classes("items-center gap-2"):
            header_source_badge = ui.badge("Origen", color="grey")
            header_dat_badge = ui.badge("DAT", color="grey")
            header_ra_badge = ui.badge("RA", color="grey")
            header_plan_badge = ui.badge("Plan", color="grey")
            header_output_badge = ui.badge("Salida", color="grey")
            ui.badge("Local", color="secondary")
            theme_button = ui.button("Oscuro", icon="dark_mode").props("dense flat").classes("rp-theme-button")

            def toggle_theme() -> None:
                enabled = not bool(state.get("dark_mode"))
                state["dark_mode"] = enabled
                dark_mode.set_value(enabled)
                theme_button.text = "Claro" if enabled else "Oscuro"
                theme_button.props(f"icon={'light_mode' if enabled else 'dark_mode'}")
                theme_button.update()

            theme_button.on_click(toggle_theme)

    with ui.column().classes(_page_class()):
        with ui.tabs().classes("w-full") as tabs:
            platform_tab = ui.tab("Plataforma", icon="category")
            setup_tab = ui.tab("Setup", icon="settings")
            dats_tab = ui.tab("Biblioteca DAT", icon="inventory_2")
            profile_tab = ui.tab("Perfil", icon="tune")
            scan_tab = ui.tab("Escaneo", icon="search")
            decisions_tab = ui.tab("Decisiones", icon="fact_check")
            plan_tab = ui.tab("Plan", icon="rule")
            summary_tab = ui.tab("Resumen", icon="dashboard")
            activity_tab = ui.tab("Actividad", icon="history")

        header_refs: dict[str, object] = {}

        def has_control_value(name: str) -> bool:
            control = header_refs.get(name)
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
            header_source_badge.color = "green" if has_control_value("source") else "grey"
            header_dat_badge.color = "green" if has_control_value("dat") else "grey"
            header_ra_badge.text = "RA" if spec.ra_active else spec.ra_label
            header_ra_badge.color = "green" if ra_cache_count(_current_platform()) else ("blue-grey" if spec.supports_ra else "grey")
            header_plan_badge.color = "green" if state.get("manifest") else "grey"
            header_output_badge.color = "green" if has_control_value("outdir") else "grey"

        def _set_tab_enabled(tab, enabled: bool) -> None:
            if enabled:
                tab.props(remove="disable")
                tab.classes(remove="opacity-50")
            else:
                tab.props("disable")
                tab.classes("opacity-50")

        def update_tab_access() -> None:
            setup_ready = bool(state.get("setup_ready"))
            has_scan = state.get("scan") is not None
            has_manifest = state.get("manifest") is not None
            _set_tab_enabled(profile_tab, setup_ready)
            _set_tab_enabled(scan_tab, setup_ready)
            _set_tab_enabled(decisions_tab, setup_ready and has_scan)
            _set_tab_enabled(plan_tab, setup_ready and has_scan)
            _set_tab_enabled(summary_tab, setup_ready and has_scan and has_manifest)

        def set_setup_ready(ready: bool) -> None:
            state["setup_ready"] = ready
            update_tab_access()
            refresh_header_status()

        def mark_setup_dirty() -> None:
            if state.get("suppress_setup_dirty"):
                return
            if state.get("setup_ready"):
                set_setup_ready(False)
            refresh_header_status()

        def switch_platform(value: str) -> None:
            new_platform = Platform(value)
            if new_platform == _current_platform():
                return
            state["platform"] = new_platform
            state["scan"] = None
            state["manifest"] = None
            state["catalog"] = None
            state["coverage"] = None
            state["overrides"] = {"main": {}, "ra": {}}
            mark_setup_dirty()
            try:
                spec = platform_spec(new_platform)
                dat_source.options = {item.id: item.label for item in list_dat_sources(new_platform.value)}
                dat_source.value = next(iter(dat_source.options), None)
                dat_source.update()
                online_table.rows = _online_dat_rows(new_platform)
                online_table.update()
                dat_table.rows = _dat_rows(new_platform)
                dat_table.update()
                platform_status.text = f"Activa: {spec.short_name}. Extensiones: {spec.extension_label}. DAT: {spec.dat_recommended}. Romset: {spec.romset_recommended}"
                refresh_platform_cards()
                refresh_setup_platform_summary()
                refresh_needed_table()
                ra_cache_status.text = _ra_status_label(new_platform)
                scan_status.text = "La plataforma ha cambiado. Valida el setup y escanea de nuevo."
                refresh_coverage()
                refresh_decisions()
            except NameError:
                pass
            update_tab_access()
            refresh_header_status()

        platform_select.on_value_change(lambda event: switch_platform(event.value))

        set_setup_ready(False)

        with ui.tab_panels(tabs, value=platform_tab).classes("w-full bg-transparent"):
            with ui.tab_panel(platform_tab).classes("p-0"):
                with ui.column().classes(_panel_class() + " mb-4"):
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
                                with ui.element("div").classes(f"rp-platform-card{active_class}").on("click", lambda _, value=row["id"]: platform_select.set_value(value)):
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
                                Path(source.value) if "source" in header_refs and source.value else None,
                                Path(dat.value) if "dat" in header_refs and dat.value else None,
                                state.get("scan"),  # type: ignore[arg-type]
                            )
                        )
                        needed_table.update()

                    refresh_needed_table()

            with ui.tab_panel(setup_tab).classes("p-0"):
                with ui.column().classes(_panel_class() + " mb-4"):
                    ui.label("Resumen de plataforma").classes("text-lg font-semibold")
                    with ui.row().classes("items-center gap-3"):
                        setup_platform_icon_box = ui.element("div")
                        with ui.column().classes("gap-0"):
                            setup_platform_title = ui.label().classes("text-lg font-semibold")
                            setup_platform_meta = ui.label().classes("text-sm text-gray-600")
                    with ui.grid().classes("w-full gap-3 grid-cols-1 md:grid-cols-2 xl:grid-cols-4"):
                        setup_platform_extensions = ui.label().classes("border border-gray-200 rounded-md p-3")
                        setup_platform_dat = ui.label().classes("border border-gray-200 rounded-md p-3")
                        setup_platform_romset = ui.label().classes("border border-gray-200 rounded-md p-3")
                        setup_platform_ra = ui.label().classes("border border-gray-200 rounded-md p-3")

                    def refresh_setup_platform_summary() -> None:
                        spec = platform_spec(_current_platform())
                        setup_platform_icon_box.clear()
                        with setup_platform_icon_box:
                            if spec.icon_url:
                                ui.image(spec.icon_url).classes("rp-platform-icon")
                            else:
                                ui.icon(spec.icon).classes("text-3xl text-primary")
                        setup_platform_title.text = spec.name
                        setup_platform_meta.text = f"{spec.brand} · {spec.generation} · {spec.kind} · {spec.dat_family}"
                        setup_platform_extensions.text = f"Extensiones: {spec.extension_label}"
                        setup_platform_dat.text = f"DAT recomendado: {spec.dat_recommended}"
                        setup_platform_romset.text = f"Romset recomendado: {spec.romset_recommended}"
                        setup_platform_ra.text = f"RetroAchievements: {spec.ra_label}"

                    refresh_setup_platform_summary()

                with ui.row().classes("w-full gap-3 mb-4"):
                    ui.label("1 Origen: carpeta con ROMs de la plataforma o ZIPs").classes("rp-step-card border border-gray-200 rounded-md p-3")
                    ui.label("2 DAT: archivo .dat/.xml o ZIP DAT-o-MATIC").classes("rp-step-card border border-gray-200 rounded-md p-3")
                    ui.label("3 Salida: carpeta destino para copy/move").classes("rp-step-card border border-gray-200 rounded-md p-3")
                    ui.label("4 Escaneo: revisar antes de aplicar").classes("rp-step-card border border-gray-200 rounded-md p-3")
                with ui.grid(columns=2).classes("w-full gap-4"):
                    with ui.column().classes(_panel_class()):
                        ui.label("Origen y salida").classes("text-lg font-semibold")
                        source = ui.input("Carpeta del romset o archivo ROM/ZIP").props("outlined readonly").classes("w-full")
                        header_refs["source"] = source
                        source_dialog = _path_picker(source, choose="any", suffixes=_source_suffixes())
                        ui.button("Buscar origen", icon="folder_open", on_click=source_dialog.open).props("color=primary").classes("w-fit")
                        outdir = ui.input("Carpeta de salida").props("outlined readonly").classes("w-full")
                        header_refs["outdir"] = outdir
                        out_dialog = _path_picker(outdir, choose="directory")
                        ui.button("Elegir salida", icon="create_new_folder", on_click=out_dialog.open).props("outline").classes("w-fit")
                        arcade_mode = ui.select(
                            {
                                "auto": "Arcade: detectar split/merged automáticamente",
                                "non-merged": "Arcade non-merged recomendado",
                                "split": "Arcade split/merged: conservar dependencias",
                            },
                            value="auto",
                            label="Modo arcade",
                        ).props("outlined").classes("w-full")

                        def save_project_click() -> None:
                            try:
                                payload = {
                                    "platform": _current_platform().value,
                                    "source": source.value or "",
                                    "dat": dat.value or "",
                                    "outdir": outdir.value or "",
                                    "arcade_mode": arcade_mode.value,
                                    "profile": _profile_from_controls(controls).model_dump(mode="json") if "profile_name" in controls else None,
                                }
                                path = _latest_project_path()
                                path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                                _log_activity(f"Sesión guardada: {path}", "OK")
                                refresh_header_status()
                            except Exception as exc:
                                _log_activity(f"No se pudo guardar sesión: {exc}", "WARN")

                        def load_project_click() -> None:
                            try:
                                path = _latest_project_path()
                                payload = json.loads(path.read_text(encoding="utf-8"))
                                state["suppress_setup_dirty"] = True
                                platform_select.set_value(payload.get("platform", _current_platform().value))
                                source.value = payload.get("source") or ""
                                dat.value = payload.get("dat") or ""
                                outdir.value = payload.get("outdir") or ""
                                arcade_mode.value = payload.get("arcade_mode") or "auto"
                                profile_payload = payload.get("profile")
                                if profile_payload and "profile_name" in controls:
                                    profile = SelectionProfile.model_validate(profile_payload)
                                    state["profile"] = profile
                                    _apply_profile_to_controls(profile, controls)
                                _log_activity(f"Sesión cargada: {path}", "OK")
                                refresh_needed_table()
                                refresh_header_status()
                                set_setup_ready(False)
                            except Exception as exc:
                                _log_activity(f"No se pudo cargar sesión: {exc}", "WARN")
                            finally:
                                state["suppress_setup_dirty"] = False
                        with ui.row().classes("items-center"):
                            ui.button("Guardar sesión", icon="save", on_click=save_project_click).props("outline")
                            ui.button("Cargar sesión", icon="folder_open", on_click=load_project_click).props("outline")

                    with ui.column().classes(_panel_class()):
                        ui.label("DAT de referencia").classes("text-lg font-semibold")
                        dat = ui.input("Archivo DAT/XML/ZIP").props("outlined readonly").classes("w-full")
                        header_refs["dat"] = dat
                        dat_dialog = _path_picker(dat, choose="file", suffixes={".dat", ".xml", ".zip"})
                        def setup_value_changed() -> None:
                            mark_setup_dirty()
                            refresh_needed_table()

                        source.on_value_change(lambda _: setup_value_changed())
                        outdir.on_value_change(lambda _: setup_value_changed())
                        dat.on_value_change(lambda _: setup_value_changed())
                        with ui.row().classes("items-center"):
                            ui.button("Buscar en el PC", icon="upload_file", on_click=dat_dialog.open).props("outline")
                            dat_status = ui.label().classes("text-sm text-gray-600")
                        def suggest_dat_click() -> None:
                            suggestion = suggest_dat_for_source(Path(source.value) if source.value else None, _current_platform())
                            if not suggestion:
                                dat_status.text = "No hay DATs instalados para sugerir. Importa o descarga uno en DATs."
                                return
                            dat.value = suggestion.path
                            dat_status.text = f"Sugerido: {suggestion.name} ({suggestion.header_mode})"
                            refresh_needed_table()

                        ui.button("Sugerir DAT según romset", icon="auto_awesome", on_click=suggest_dat_click).props("outline").classes("w-fit")
                        source_options = {item.id: item.label for item in list_dat_sources(_current_platform().value)}
                        dat_source = ui.select(source_options, value=next(iter(source_options)), label="Descargar DAT").props("outlined").classes("w-full")

                        async def download_dat_click() -> None:
                            try:
                                imported = await asyncio.to_thread(download_and_import_source, dat_source.value)
                                dat.value = imported[0].path
                                dat_status.text = f"DAT descargado e importado: {imported[0].name}"
                                refresh_dat_table()
                                refresh_needed_table()
                            except Exception as exc:
                                dat_status.text = f"No se pudo descargar: {exc}"

                        ui.button("Descargar seleccionado", icon="download", on_click=download_dat_click).props("color=primary").classes("w-fit")
                        validation_status = ui.label().classes("text-sm text-gray-600")

                        async def validate_click() -> None:
                            validation_status.text = "Validando configuración..."
                            issues = await asyncio.to_thread(
                                validate_setup,
                                Path(source.value) if source.value else None,
                                Path(dat.value) if dat.value else None,
                                Path(outdir.value) if outdir.value else None,
                            )
                            ready = not issues
                            set_setup_ready(ready)
                            validation_status.text = "Configuración lista. Ya puedes continuar con Perfil, Escaneo y Plan." if ready else " · ".join(issues)

                        ui.button("Validar configuración", icon="verified", on_click=validate_click).props("outline").classes("w-fit")

                with ui.column().classes(_panel_class() + " mt-4"):
                    ui.label("RetroAchievements").classes("text-lg font-semibold")
                    ui.label("RA se comprueba por hash: primero cachea la lista oficial de la plataforma y, tras escanear, marca cada ROM que coincida. Los detalles de parches usan Supported Game Files y guardan labels/PatchUrl localmente.").classes("text-sm text-gray-600")
                    ui.label("Límite detalles: un valor bajo va bien para pruebas rápidas. Para mejorar la detección de parches y acercarse a una colección RA perfecta, súbelo hasta cubrir todos los juegos cacheados de la plataforma.").classes("text-sm text-gray-600")
                    ra_cache_status = ui.label(_ra_status_label(_current_platform())).classes("text-sm text-gray-600")
                    with ui.row().classes("w-full gap-3"):
                        username = ui.input("Usuario").props("outlined").classes("min-w-72")
                        api_key = ui.input("API key", password=True).props("outlined").classes("min-w-96")
                        details_limit = ui.number("Límite detalles", value=150, min=1, max=2000, step=50).props("outlined").classes("w-40")
                        details_delay = ui.number("Pausa RA (s)", value=1.2, min=0.5, max=10, step=0.1).props("outlined").classes("w-40")
                    ra_status = ui.label(f"Credenciales: {'configuradas' if credentials_path().exists() else 'pendientes'}").classes("text-sm text-gray-600")
                    ra_details_progress = ui.linear_progress(value=0, show_value=False).props("instant-feedback").classes("w-full")
                    ra_details_progress_label = ui.label("Detalles RA: 0% · 0 / 0 juegos · 0 hashes actualizados").classes("text-sm text-gray-600")

                    async def sync_ra_click() -> None:
                        if not username.value or not api_key.value:
                            ra_status.text = "Introduce usuario y API key para sincronizar."
                            return
                        try:
                            save_credentials(username.value, api_key.value)
                            platform = _current_platform()
                            ra_status.text = "Sincronizando hashes RA..."
                            count = await asyncio.to_thread(sync_ra_hashes, platform, username.value, api_key.value)
                            ra_status.text = f"Listo: {count} hashes RA cacheados."
                            ra_cache_status.text = _ra_status_label(platform)
                            refresh_header_status()
                        except Exception as exc:
                            ra_status.text = f"Error RA: {exc}"

                    async def sync_ra_details_click() -> None:
                        try:
                            platform = _current_platform()
                            state["ra_details_progress"] = {"current": 0, "total": int(details_limit.value or 150), "updated": 0, "running": True}
                            ra_status.text = "Sincronizando detalles RA: labels, nombres de hash y PatchUrl..."
                            def progress_update(update: dict[str, int]) -> None:
                                state["ra_details_progress"] = {**update, "running": True}

                            count = await asyncio.to_thread(
                                sync_ra_patch_details,
                                platform,
                                username.value or None,
                                api_key.value or None,
                                None,
                                int(details_limit.value or 150),
                                None,
                                progress_update,
                                float(details_delay.value or 1.2),
                            )
                            current_progress = state.get("ra_details_progress", {})
                            total = int(current_progress.get("total", 0) or 0)
                            state["ra_details_progress"] = {"current": total, "total": total, "updated": count, "running": False}
                            scan_result = state.get("scan")
                            if scan_result is not None:
                                state["scan"] = await asyncio.to_thread(annotate_scan_with_ra, scan_result)
                            ra_status.text = f"Detalles RA actualizados: {count}. Puedes continuar luego; se priorizan pendientes. 🩹 indica hash con parche localizado."
                            _log_activity(f"Detalles RA actualizados para {platform_spec(platform).short_name}: {count}", "OK")
                            ra_cache_status.text = _ra_status_label(platform)
                            refresh_coverage()
                            refresh_decisions()
                        except Exception as exc:
                            current = cast(dict[str, object], state.get("ra_details_progress") or {})
                            state["ra_details_progress"] = {**current, "running": False}
                            ra_status.text = f"Error detalles RA: {exc}"

                    with ui.row().classes("items-center gap-2"):
                        ui.button("Guardar y sincronizar hashes", icon="sync", on_click=sync_ra_click).props("color=primary")
                        ui.button("Localizar parches RA", icon="healing", on_click=sync_ra_details_click).props("outline")

                        async def complete_details_click() -> None:
                            status = ra_sync_status(_current_platform())
                            remaining = int(status.get("remaining_details", 0) or 0)
                            cached = int(status.get("cached_games", 0) or 0)
                            target = cached if cached else int(details_limit.value or 150)
                            details_limit.value = max(1, min(2000, target))
                            details_limit.update()
                            ra_status.text = f"Límite ajustado a {details_limit.value}. Pendientes estimados: {remaining}. Iniciando detalles..."
                            await sync_ra_details_click()

                        ui.button("Continuar pendientes RA", icon="done_all", on_click=complete_details_click).props("outline")

                    def refresh_ra_details_progress() -> None:
                        progress = state.get("ra_details_progress", {})
                        current = int(progress.get("current", 0) or 0)
                        total = int(progress.get("total", 0) or 0)
                        updated = int(progress.get("updated", 0) or 0)
                        value = current / total if total else 0
                        ra_details_progress.value = value
                        percent = round(value * 100)
                        ra_details_progress_label.text = f"Detalles RA: {percent}% · {current} / {total} juegos · {updated} hashes actualizados"

                    ui.timer(0.3, refresh_ra_details_progress)

            with ui.tab_panel(dats_tab).classes("p-0"), ui.column().classes(_panel_class()):
                ui.label("Biblioteca de DATs").classes("text-lg font-semibold")
                dat_manager_status = ui.label("Aqui se descargan/importan DATs, se registran con metadatos y se elige cual usar para el escaneo actual.").classes("text-sm text-gray-600")
                ui.label("Fuentes online").classes("text-md font-semibold")
                online_table = ui.table(
                    columns=[
                        {"name": "label", "label": "Fuente", "field": "label", "sortable": True, "align": "left"},
                        {"name": "format", "label": "Formato", "field": "format", "align": "left"},
                        {"name": "direct", "label": "Descarga directa", "field": "direct", "sortable": True},
                        {"name": "notes", "label": "Notas", "field": "notes", "align": "left"},
                    ],
                    rows=_online_dat_rows(_current_platform()),
                    row_key="id",
                    selection="single",
                    pagination=6,
                ).classes("w-full rp-table-card")

                async def download_online_click() -> None:
                    selected = online_table.selected
                    if not selected:
                        dat_manager_status.text = "Selecciona una fuente online."
                        return
                    try:
                        imported = await asyncio.to_thread(download_and_import_source, selected[0]["id"])
                        dat.value = imported[0].path
                        dat_manager_status.text = f"Descargados/importados {len(imported)} DATs. Activo: {imported[0].name}"
                        refresh_dat_table()
                    except Exception as exc:
                        dat_manager_status.text = f"No se pudo descargar automáticamente: {exc}"

                def open_online_click() -> None:
                    selected = online_table.selected
                    if not selected:
                        dat_manager_status.text = "Selecciona una fuente online."
                        return
                    webbrowser.open(selected[0]["url"])
                    dat_manager_status.text = "Fuente abierta en el navegador. Si descarga un ZIP, impórtalo aquí."

                custom_url = ui.input("URL directa a DAT/XML/ZIP").props("outlined").classes("w-full")
                custom_filename = ui.input("Nombre de archivo opcional").props("outlined").classes("w-96")

                async def download_url_click() -> None:
                    if not custom_url.value:
                        dat_manager_status.text = "Introduce una URL directa."
                        return
                    try:
                        imported = await asyncio.to_thread(download_and_import_url, custom_url.value, custom_filename.value or None)
                        dat.value = imported[0].path
                        dat_manager_status.text = f"URL descargada/importada: {imported[0].name}"
                        refresh_dat_table()
                    except Exception as exc:
                        dat_manager_status.text = f"No se pudo descargar la URL: {exc}"

                with ui.row():
                    ui.button("Descargar fuente", icon="download", on_click=download_online_click).props("color=primary")
                    ui.button("Abrir fuente", icon="open_in_browser", on_click=open_online_click).props("outline")
                    ui.button("Descargar URL", icon="link", on_click=download_url_click).props("outline")

                ui.separator()
                ui.label("Descarga por lote").classes("text-md font-semibold")
                ui.label("Automático usa fuentes directas públicas. DAT-o-MATIC queda como fuente oficial asistida cuando requiere navegador o sesión.").classes("text-sm text-gray-600")
                with ui.row().classes("items-end gap-3"):
                    batch_scope = ui.select(
                        {"current": "Solo plataforma actual", "all": "Todas con fuente directa"},
                        value="current",
                        label="Alcance",
                    ).props("outlined").classes("w-64")
                    batch_limit = ui.number("Límite", value=20, min=1, max=300, step=10).props("outlined").classes("w-32")
                    batch_progress = ui.linear_progress(value=0, show_value=False).props("instant-feedback").classes("w-64")
                batch_table = ui.table(
                    columns=[
                        {"name": "platform", "label": "Plataforma", "field": "platform", "sortable": True, "align": "left"},
                        {"name": "source", "label": "Fuente", "field": "source", "align": "left"},
                        {"name": "status", "label": "Estado", "field": "status", "sortable": True, "align": "center"},
                    ],
                    rows=[],
                    pagination=6,
                ).props("dense flat bordered wrap-cells").classes("w-full compact-table")

                async def batch_download_click() -> None:
                    source_ids = _direct_dat_batch_candidates(batch_scope.value, _current_platform(), int(batch_limit.value or 20))
                    if not source_ids:
                        dat_manager_status.text = "No hay fuentes directas para este alcance."
                        return
                    rows = []
                    for source_id in source_ids:
                        source_item = next(item for item in DAT_SOURCES if item.id == source_id)
                        rows.append({"platform": platform_spec(source_item.platform).short_name, "source": source_item.label, "status": "pendiente"})
                    batch_table.rows = rows
                    batch_table.update()
                    imported_total = 0
                    for index, source_id in enumerate(source_ids, start=1):
                        source_item = next(item for item in DAT_SOURCES if item.id == source_id)
                        batch_progress.value = (index - 1) / len(source_ids)
                        try:
                            imported = await asyncio.to_thread(download_and_import_source, source_id)
                            imported_total += len(imported)
                            rows[index - 1]["status"] = f"OK ({len(imported)})"
                            dat_manager_status.text = f"Descargado {index}/{len(source_ids)}: {source_item.label}"
                        except Exception as exc:
                            rows[index - 1]["status"] = f"Error: {exc}"
                        batch_table.rows = rows
                        batch_table.update()
                    batch_progress.value = 1
                    dat_manager_status.text = f"Lote terminado: {imported_total} DATs importados de {len(source_ids)} fuentes."
                    _log_activity(f"Lote DAT terminado: {imported_total} DATs importados", "OK")
                    refresh_dat_table()
                    refresh_needed_table()

                ui.button("Descargar lote directo", icon="cloud_download", on_click=batch_download_click).props("outline")

                ui.separator()
                ui.label("DAT-o-MATIC: cobertura pendiente en RetroPerfect").classes("text-md font-semibold")
                ui.label("La lista se basa en la tabla pública de sistemas de No-Intro; DAT-o-MATIC puede variar y algunos sistemas privados requieren sesión.").classes("text-sm text-gray-600")
                ui.table(
                    columns=[
                        {"name": "group", "label": "Grupo", "field": "group", "sortable": True, "align": "left"},
                        {"name": "platform", "label": "Plataformas/variantes", "field": "platform", "align": "left"},
                        {"name": "status", "label": "Estado", "field": "status", "sortable": True, "align": "center"},
                    ],
                    rows=DATOMATIC_GAP_ROWS,
                    pagination=8,
                ).props("dense flat bordered wrap-cells").classes("w-full compact-table")

                ui.separator()
                ui.label("Importación local").classes("text-md font-semibold")
                import_path = ui.input("Archivo DAT/XML/ZIP a importar").props("outlined readonly").classes("w-full")
                import_dialog = _path_picker(import_path, choose="file", suffixes={".dat", ".xml", ".zip"})
                with ui.row():
                    ui.button("Buscar DAT/ZIP", icon="upload_file", on_click=import_dialog.open).props("outline")

                    async def import_click() -> None:
                        if not import_path.value:
                            dat_manager_status.text = "Selecciona un DAT, XML o ZIP."
                            return
                        try:
                            imported = await asyncio.to_thread(import_dat_file, Path(import_path.value))
                            dat.value = imported[0].path
                            dat_manager_status.text = f"Importados {len(imported)} DATs. Usando: {imported[0].name}"
                            refresh_dat_table()
                        except Exception as exc:
                            dat_manager_status.text = f"No se pudo importar: {exc}"

                    ui.button("Importar", icon="archive", on_click=import_click).props("color=primary")
                dat_table = ui.table(
                    columns=[
                        {"name": "name", "label": "Nombre", "field": "name", "sortable": True, "align": "left"},
                        {"name": "platform", "label": "Plataforma", "field": "platform", "sortable": True, "align": "left"},
                        {"name": "source", "label": "Fuente", "field": "source", "sortable": True, "align": "left"},
                        {"name": "format", "label": "Formato", "field": "format", "sortable": True, "align": "left"},
                        {"name": "games", "label": "Juegos", "field": "games", "sortable": True, "align": "right"},
                        {"name": "roms", "label": "ROMs", "field": "roms", "sortable": True, "align": "right"},
                        {"name": "pc", "label": "P/C", "field": "pc", "sortable": True, "align": "center"},
                        {"name": "header", "label": "Header", "field": "header", "sortable": True, "align": "center"},
                        {"name": "recommended", "label": "Recomendado", "field": "recommended", "sortable": True, "align": "center"},
                        {"name": "regions", "label": "Regiones", "field": "regions", "align": "left"},
                        {"name": "notes", "label": "Notas", "field": "notes", "align": "left"},
                    ],
                    rows=[],
                    row_key="id",
                    selection="multiple",
                    pagination=12,
                ).classes("w-full rp-table-card")
                compare_status = ui.label().classes("text-sm text-gray-600")

                def refresh_dat_table() -> None:
                    dat_table.rows = _dat_rows(_current_platform())
                    dat_table.update()

                def use_selected_dat() -> None:
                    selected = dat_table.selected
                    if not selected:
                        dat_manager_status.text = "Selecciona un DAT instalado."
                        return
                    dat.value = selected[0]["path"]
                    dat_manager_status.text = f"DAT activo: {selected[0]['name']}"

                def compare_selected_dats() -> None:
                    selected = dat_table.selected
                    if len(selected) != 2:
                        compare_status.text = "Selecciona exactamente dos DATs para comparar."
                        return
                    try:
                        comparison = compare_dats(Path(selected[0]["path"]), Path(selected[1]["path"]))
                        compare_status.text = (
                            f"{comparison.left_name} vs {comparison.right_name}: "
                            f"comunes {comparison.common_games} juegos / {comparison.common_roms} ROMs; "
                            f"solo primero {comparison.left_only_games} juegos / {comparison.left_only_roms} ROMs; "
                            f"solo segundo {comparison.right_only_games} juegos / {comparison.right_only_roms} ROMs."
                        )
                    except Exception as exc:
                        compare_status.text = f"No se pudo comparar: {exc}"

                with ui.row():
                    ui.button("Usar seleccionado", icon="check", on_click=use_selected_dat).props("color=primary")
                    ui.button("Comparar dos DATs", icon="compare_arrows", on_click=compare_selected_dats).props("outline")
                    ui.button("Refrescar", icon="refresh", on_click=refresh_dat_table).props("flat")
                refresh_dat_table()

            with ui.tab_panel(profile_tab).classes("p-0"):
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
                            state["profile"] = _profile_from_controls(controls)
                            profile_status.text = "Perfil actualizado."
                        except ValidationError as exc:
                            profile_status.text = f"Perfil inválido: {exc}"

                    def persist_profile_click() -> None:
                        try:
                            profile = _profile_from_controls(controls)
                            path = save_named_profile(profile)
                            state["profile"] = profile
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
                            state["profile"] = profile
                            _apply_profile_to_controls(profile, controls)
                            profile_status.text = f"Perfil cargado: {profile.name}"
                        except Exception as exc:
                            profile_status.text = f"No se pudo cargar: {exc}"

                    def apply_recommended_profile_click() -> None:
                        try:
                            profile = list_recommended_profiles()[recommended_profile.value]
                            state["profile"] = profile
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
                        profile_compare_table.rows = _profile_comparison_rows(state.get("scan"), outdir.value)
                        profile_compare_table.update()
                        if not profile_compare_table.rows:
                            profile_status.text = "Escanea primero para comparar perfiles."
                            return
                        profile_status.text = "Comparación actualizada."
                        _log_activity("Comparador de perfiles actualizado", "INFO")

                    ui.button("Comparar presets con este escaneo", icon="compare", on_click=compare_profiles_click).props("outline")

            with ui.tab_panel(scan_tab).classes("p-0"), ui.column().classes(_panel_class()):
                ui.label("Configuración activa").classes("text-lg font-semibold")
                with ui.grid(columns=4).classes("w-full gap-3"):
                    active_platform = ui.label("Plataforma: NES / Famicom").classes("border border-gray-200 rounded-md p-3")
                    active_source = ui.label("Origen: sin seleccionar").classes("border border-gray-200 rounded-md p-3")
                    active_dat = ui.label("DAT: sin seleccionar").classes("border border-gray-200 rounded-md p-3")
                    active_out = ui.label("Salida: sin seleccionar").classes("border border-gray-200 rounded-md p-3")
                def refresh_active_config() -> None:
                    active_platform.text = f"Plataforma: {platform_spec(_current_platform()).short_name}"
                    active_source.text = f"Origen: {source.value or 'sin seleccionar'}"
                    active_dat.text = f"DAT: {dat.value or 'sin seleccionar'}"
                    active_out.text = f"Salida: {outdir.value or 'sin seleccionar'}"

                scan_status = ui.label("Sin escaneo todavía.").classes("text-sm text-gray-600")
                scan_progress = ui.linear_progress(value=0, show_value=False).props("instant-feedback").classes("w-full")
                scan_progress_label = ui.label("0% · 0 / 0 archivos · 0 ROMs · 0 matches").classes("text-sm text-gray-600")
                scan_current_file = ui.label("").classes("text-xs text-gray-500")
                diagnostic_table = ui.table(
                    columns=[
                        {"name": "status", "label": "", "field": "status", "align": "center"},
                        {"name": "item", "label": "Chequeo", "field": "item", "sortable": True, "align": "left"},
                        {"name": "detail", "label": "Resultado", "field": "detail", "align": "left"},
                        {"name": "recommendation", "label": "Qué hacer", "field": "recommendation", "align": "left"},
                    ],
                    rows=[],
                    pagination=5,
                ).props("dense flat bordered wrap-cells").classes("w-full compact-table")
                diagnostic_table.add_slot(
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
                scan_table = ui.table(
                    columns=[
                        {"name": "file", "label": "Archivo", "field": "file", "sortable": True, "align": "left"},
                        {"name": "dat", "label": "DAT", "field": "dat", "sortable": True, "align": "left"},
                        {"name": "ra", "label": "RA", "field": "ra", "sortable": True, "align": "center"},
                        {"name": "region", "label": "Región", "field": "region", "align": "center"},
                        {"name": "tags", "label": "Tags", "field": "tags", "align": "right"},
                    ],
                    rows=[],
                    pagination=15,
                ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")
                scan_table.add_slot("body-cell-ra", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
                scan_table.add_slot("body-cell-region", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')
                scan_table.add_slot("body-cell-tags", '<q-td :props="props" class="rp-right">{{ props.value }}</q-td>')
                ui.label("No coincidencias y duplicados").classes("text-md font-semibold")
                with ui.grid(columns=2).classes("w-full gap-3"):
                    unmatched_table = ui.table(
                        columns=[
                            {"name": "type", "label": "Tipo", "field": "type", "sortable": True, "align": "left"},
                            {"name": "file", "label": "Archivo", "field": "file", "sortable": True, "align": "left"},
                            {"name": "region", "label": "Región", "field": "region", "align": "center"},
                            {"name": "md5", "label": "MD5", "field": "md5", "align": "left"},
                            {"name": "suggestion", "label": "Sugerencia", "field": "suggestion", "align": "left"},
                        ],
                        rows=[],
                        pagination=6,
                    ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")
                    duplicate_table = ui.table(
                        columns=[
                            {"name": "kind", "label": "Tipo", "field": "kind", "sortable": True, "align": "left"},
                            {"name": "game", "label": "Juego", "field": "game", "sortable": True, "align": "left"},
                            {"name": "count", "label": "N", "field": "count", "sortable": True, "align": "right"},
                            {"name": "detail", "label": "Detalle", "field": "detail", "align": "left"},
                        ],
                        rows=[],
                        pagination=6,
                    ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")
                    unmatched_table.add_slot("body-cell-region", '<q-td :props="props" class="rp-center">{{ props.value }}</q-td>')

                async def scan_click() -> None:
                    refresh_active_config()
                    if not source.value:
                        scan_status.text = "Selecciona un origen antes de escanear."
                        return
                    try:
                        state["scan_progress"] = {"current": 0, "total": 0, "path": "", "roms": 0, "matched": 0, "phase": "preparing"}
                        dat_path = Path(dat.value) if dat.value else None
                        if dat_path and dat_path.suffix.lower() == ".zip":
                            imported = await asyncio.to_thread(import_dat_file, dat_path)
                            dat_path = Path(imported[0].path)
                            try:
                                state["suppress_setup_dirty"] = True
                                dat.value = str(dat_path)
                            finally:
                                state["suppress_setup_dirty"] = False
                        scan_status.text = "Cargando e indexando DAT..."
                        catalog = await asyncio.to_thread(parse_dat, dat_path) if dat_path else None
                        dat_index = await asyncio.to_thread(DatIndex, catalog) if catalog else None
                        scan_status.text = "Escaneando ZIPs/ROMs... en romsets grandes puede tardar unos minutos."

                        def progress_update(update: dict[str, object]) -> None:
                            state["scan_progress"] = update

                        result = await asyncio.to_thread(
                            scan_directory,
                            Path(source.value),
                            _current_platform(),
                            dat_index,
                            dat_path,
                            progress_update,
                            project_state_dir() / "scan-cache.sqlite3",
                        )
                        result = await asyncio.to_thread(annotate_scan_with_ra, result)
                        save_scan(result)
                        state["scan"] = result
                        state["catalog"] = catalog
                        state["coverage"] = build_coverage(result, catalog)
                        update_tab_access()
                        scan_table.rows = [
                            {
                                "file": Path(rom.container_path).name if not rom.inner_path else f"{Path(rom.container_path).name} / {rom.inner_path}",
                                "dat": rom.dat_game.name if rom.dat_game else "",
                                "ra": " ".join(part for part in [_ra_icon(rom), rom.ra_title or rom.ra_hash_name or ""] if part),
                                "region": _flag_regions(rom.metadata.regions),
                                "tags": ", ".join(rom.metadata.tags),
                            }
                            for rom in result.roms
                        ]
                        scan_table.update()
                        unmatched_table.rows = _unmatched_rows(result)
                        unmatched_table.update()
                        duplicate_table.rows = _duplicate_rows(result)
                        duplicate_table.update()
                        ra_matches = sum(1 for rom in result.roms if rom.ra_game_id)
                        scan_status.text = f"Escaneados {len(result.roms)} candidatos. Coincidencias RA: {ra_matches}. No reconocidos: {len(result.unmatched_files)}."
                        _log_activity(f"Escaneo completado: {len(result.roms)} ROMs, {ra_matches} RA, {len(result.unmatched_files)} no reconocidos", "OK")
                        refresh_needed_table()
                        refresh_coverage()
                        refresh_decisions()
                    except Exception as exc:
                        scan_status.text = f"Error de escaneo: {exc}"

                with ui.row():
                    ui.button("Actualizar configuración", icon="refresh", on_click=refresh_active_config).props("outline")
                    def diagnostic_click() -> None:
                        refresh_active_config()
                        diagnostic_table.rows = _diagnostic_rows(
                            build_needed_rows(
                                _current_platform(),
                                Path(source.value) if source.value else None,
                                Path(dat.value) if dat.value else None,
                                state.get("scan"),  # type: ignore[arg-type]
                            )
                        )
                        diagnostic_table.update()
                        scan_status.text = "Diagnóstico actualizado. Si ves WARN/MISS, corrige eso antes de escanear."
                        _log_activity("Diagnóstico rápido actualizado", "INFO")

                    ui.button("Diagnóstico rápido", icon="troubleshoot", on_click=diagnostic_click).props("outline")
                    ui.button("Escanear colección", icon="search", on_click=scan_click).props("color=primary")

                def refresh_scan_progress() -> None:
                    progress = state.get("scan_progress", {})
                    current = int(progress.get("current", 0) or 0)
                    total = int(progress.get("total", 0) or 0)
                    roms = int(progress.get("roms", 0) or 0)
                    matched = int(progress.get("matched", 0) or 0)
                    value = current / total if total else 0
                    scan_progress.value = value
                    percent = round(value * 100)
                    scan_progress_label.text = f"{percent}% · {current} / {total} archivos · {roms} ROMs · {matched} matches"
                    current_path = str(progress.get("path", "") or "")
                    scan_current_file.text = f"Procesando: {Path(current_path).name}" if current_path else ""

                ui.timer(0.3, refresh_scan_progress)

            with ui.tab_panel(summary_tab).classes("p-0"), ui.column().classes(_panel_class()):
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
                    summary = state.get("coverage")
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
                                Path(source.value) if source.value else None,
                                Path(dat.value) if dat.value else None,
                                None,
                            )
                        )
                        dat_warning_table.update()
                        patch_queue_table.rows = []
                        patch_queue_table.update()
                        return
                    audit = build_perfect_audit(summary, state.get("scan"), state.get("manifest"))  # type: ignore[arg-type]
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
                            Path(source.value) if source.value else None,
                            Path(dat.value) if dat.value else None,
                            state.get("scan"),  # type: ignore[arg-type]
                        )
                    )
                    dat_warning_table.update()
                    patch_queue_table.rows = _patch_queue_rows(state.get("manifest"))
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
                        coverage_table.rows = _coverage_variant_rows(state.get("scan"), state.get("catalog"), state.get("manifest"), coverage_filter.value)
                    else:
                        coverage_table.rows = _coverage_rows(summary, coverage_filter.value, state.get("scan"), state.get("manifest"))
                    coverage_table.update()

                coverage_filter.on_value_change(lambda _: refresh_coverage())
                coverage_view.on_value_change(lambda _: refresh_coverage())

            with ui.tab_panel(decisions_tab).classes("p-0"), ui.column().classes(_panel_class()):
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
                    groups_table.rows = _group_rows(state.get("scan"))
                    groups_table.update()
                    if selected_group["key"]:
                        variants_table.rows = _variant_rows(state.get("scan"), selected_group["key"], state["profile"])  # type: ignore[arg-type]
                        variants_table.update()

                def select_group(event) -> None:
                    row = event.args[1] if isinstance(event.args, list) and len(event.args) > 1 else event.args
                    selected_group["key"] = row.get("group", "") if isinstance(row, dict) else ""
                    variants_table.rows = _variant_rows(state.get("scan"), selected_group["key"], state["profile"])  # type: ignore[arg-type]
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
                    state["overrides"].setdefault(bucket, {})[selected_group["key"]] = rom_id  # type: ignore[union-attr]
                    decision_status.text = f"Override {bucket} aplicado."
                    refresh_decisions()

                def clear_override(bucket: str) -> None:
                    if selected_group["key"]:
                        state["overrides"].setdefault(bucket, {}).pop(selected_group["key"], None)  # type: ignore[union-attr]
                    decision_status.text = f"Override {bucket} eliminado."
                    refresh_decisions()

                with ui.row():
                    ui.button("Usar variante en main", icon="bookmark", on_click=lambda: set_override("main")).props("color=primary")
                    ui.button("Usar variante en RA", icon="emoji_events", on_click=lambda: set_override("ra")).props("outline")
                    ui.button("Quitar override main", icon="backspace", on_click=lambda: clear_override("main")).props("flat")
                    ui.button("Quitar override RA", icon="backspace", on_click=lambda: clear_override("ra")).props("flat")

            with ui.tab_panel(plan_tab).classes("p-0"):
                with ui.column().classes(_panel_class()):
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
                                manifest = state["manifest"]
                                if manifest is None:
                                    plan_status.text = "No hay manifiesto que aplicar."
                                    safety_dialog.close()
                                    return
                                try:
                                    completed = await asyncio.to_thread(apply_manifest, manifest, None, True)  # type: ignore[arg-type]
                                    plan_status.text = f"Aplicadas {len(completed)} operaciones."
                                    safety_dialog.close()
                                except Exception as exc:
                                    plan_status.text = f"No se aplicó: {exc}"
                                    safety_dialog.close()

                            ui.button("Aplicar manifiesto", icon="play_arrow", on_click=confirm_apply_click).props("color=secondary")

                    async def plan_click() -> None:
                        scan_result = state["scan"]
                        if scan_result is None:
                            plan_status.text = "Escanea una colección antes de crear el plan."
                            return
                        try:
                            state["profile"] = _profile_from_controls(controls)
                            profile = state["profile"]
                            manifest = build_manifest(
                                scan_result,  # type: ignore[arg-type]
                                profile,  # type: ignore[arg-type]
                                [output.bucket for output in profile.outputs],  # type: ignore[attr-defined]
                                output_dir=Path(outdir.value) if outdir.value else None,
                                action=ActionMode(action.value),
                                overrides=state["overrides"],  # type: ignore[arg-type]
                            )
                            path = save_manifest(manifest, Path(".retroperfect/manifests/latest.json"))
                            state["manifest"] = manifest
                            state["coverage"] = build_coverage(scan_result, state.get("catalog"), manifest)  # type: ignore[arg-type]
                            update_tab_access()
                            plan_table.rows = [
                                {
                                    "bucket": entry.bucket.value,
                                    "source": Path(entry.source_path).name,
                                    "destination": str(Path(entry.destination_path).relative_to(Path(outdir.value))) if entry.destination_path and outdir.value else (entry.destination_path or ""),
                                    "icons": _plan_reason_icons(entry.explanation),
                                }
                                for entry in manifest.entries
                            ]
                            plan_table.update()
                            divergence_table.rows = _bucket_divergence_rows(scan_result, manifest)
                            divergence_table.update()
                            ra_conflict_table.rows = _ra_conflict_rows(scan_result, manifest)
                            ra_conflict_table.update()
                            export_tree_table.rows = _export_tree_rows(manifest, outdir.value)
                            export_tree_table.update()
                            plan_status.text = f"Manifiesto guardado en {path}"
                            refresh_coverage()
                        except Exception as exc:
                            plan_status.text = f"Error creando plan: {exc}"

                    async def safe_plan_click() -> None:
                        scan_result = state["scan"]
                        if scan_result is None:
                            plan_status.text = "Escanea una colección antes de crear una prueba segura."
                            return
                        if not outdir.value:
                            plan_status.text = "El modo prueba segura necesita carpeta de salida."
                            return
                        try:
                            sample = _scan_group_sample(scan_result, int(safe_sample_limit.value or 25))
                            if sample is None:
                                plan_status.text = "No hay datos de escaneo para muestrear."
                                return
                            state["profile"] = _profile_from_controls(controls)
                            profile = state["profile"]
                            manifest = build_manifest(
                                sample,
                                profile,  # type: ignore[arg-type]
                                [output.bucket for output in profile.outputs],  # type: ignore[attr-defined]
                                output_dir=Path(outdir.value) / "_prueba_segura",
                                action=ActionMode.COPY,
                                overrides=state["overrides"],  # type: ignore[arg-type]
                            )
                            path = save_manifest(manifest, Path(".retroperfect/manifests/latest-safe-sample.json"))
                            state["manifest"] = manifest
                            state["coverage"] = build_coverage(scan_result, state.get("catalog"), manifest)  # type: ignore[arg-type]
                            action.value = ActionMode.COPY.value
                            action.update()
                            plan_table.rows = [
                                {
                                    "bucket": entry.bucket.value,
                                    "source": Path(entry.source_path).name,
                                    "destination": str(Path(entry.destination_path).relative_to(Path(outdir.value))) if entry.destination_path and outdir.value else (entry.destination_path or ""),
                                    "icons": _plan_reason_icons(entry.explanation),
                                }
                                for entry in manifest.entries
                            ]
                            plan_table.update()
                            divergence_table.rows = _bucket_divergence_rows(sample, manifest)
                            divergence_table.update()
                            ra_conflict_table.rows = _ra_conflict_rows(sample, manifest)
                            ra_conflict_table.update()
                            export_tree_table.rows = _export_tree_rows(manifest, outdir.value)
                            export_tree_table.update()
                            update_tab_access()
                            refresh_coverage()
                            _log_activity(f"Prueba segura creada: {len(manifest.entries)} operaciones", "OK")
                            plan_status.text = f"Prueba segura guardada en {path}. Solo copia en _prueba_segura."
                        except Exception as exc:
                            plan_status.text = f"Error creando prueba segura: {exc}"

                    async def apply_click() -> None:
                        manifest = state["manifest"]
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
                        manifest = state["manifest"]
                        if manifest is None:
                            plan_status.text = "No hay manifiesto para reportar."
                            return
                        path = report_manifest(manifest, Path(".retroperfect/reports/latest.html"), "html")  # type: ignore[arg-type]
                        plan_status.text = f"Reporte generado en {path}"

                    summary_actions["plan"] = plan_click
                    summary_actions["apply"] = apply_click

                    with ui.row():
                        ui.button("Crear manifiesto", icon="rule", on_click=plan_click).props("color=primary")
                        ui.button("Crear prueba segura", icon="science", on_click=safe_plan_click).props("outline")
                        ui.button("Generar reporte", icon="article", on_click=report_click).props("outline")
                        ui.button("Abrir salida", icon="folder_open", on_click=lambda: _open_path(outdir.value)).props("outline")
                        ui.button("Abrir reportes", icon="topic", on_click=lambda: _open_path(Path(".retroperfect/reports"))).props("outline")
                        ui.button("Aplicar", icon="play_arrow", on_click=apply_click).props("color=secondary")

            with ui.tab_panel(activity_tab).classes("p-0"), ui.column().classes(_panel_class()):
                ui.label("Actividad").classes("text-lg font-semibold")
                ui.label("Registro local de acciones importantes de esta sesión: diagnósticos, escaneos, descargas DAT, planes y RA.").classes("text-sm text-gray-600")
                activity_table = ui.table(
                    columns=[
                        {"name": "time", "label": "Hora", "field": "time", "sortable": True, "align": "center"},
                        {"name": "level", "label": "Tipo", "field": "level", "sortable": True, "align": "center"},
                        {"name": "message", "label": "Mensaje", "field": "message", "align": "left"},
                    ],
                    rows=_activity_rows(),
                    pagination=12,
                ).props("dense flat bordered wrap-cells").classes("w-full compact-table rp-table-card")

                def refresh_activity() -> None:
                    activity_table.rows = _activity_rows()
                    activity_table.update()

                with ui.row():
                    ui.button("Refrescar", icon="refresh", on_click=refresh_activity).props("outline")
                    ui.button("Abrir carpeta del proyecto", icon="folder_open", on_click=lambda: _open_path(project_state_dir())).props("outline")

                ui.timer(1.0, refresh_activity)


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
