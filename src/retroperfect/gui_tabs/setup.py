"""Pestaña Setup: origen, salida, DAT activo y RetroAchievements."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nicegui import ui

from ..dat_manager import download_and_import_source, suggest_dat_for_source, validate_setup
from ..dat_sources import list_dat_sources
from ..gui_context import UiContext
from ..gui_rows import (
    _apply_profile_to_controls,
    _latest_project_path,
    _panel_class,
    _profile_from_controls,
    _ra_status_label,
    _source_suffixes,
)
from ..gui_state import _current_platform, _log_activity, busy, state
from ..gui_widgets import _path_picker
from ..models import SelectionProfile
from ..platforms import platform_spec
from ..ra import annotate_scan_with_ra, credentials_path, ra_sync_status, save_credentials, sync_ra_hashes, sync_ra_patch_details


def build(ctx: UiContext) -> None:
    with ui.tab_panel(ctx.setup_tab).classes("p-0"):
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
                ctx.header_refs["source"] = source
                source_dialog = _path_picker(source, choose="any", suffixes=_source_suffixes())
                ui.button("Buscar origen", icon="folder_open", on_click=source_dialog.open).props("color=primary").classes("w-fit")
                outdir = ui.input("Carpeta de salida").props("outlined readonly").classes("w-full")
                ctx.header_refs["outdir"] = outdir
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
                            "profile": _profile_from_controls(ctx.controls).model_dump(mode="json") if ctx.controls and "profile_name" in ctx.controls else None,
                        }
                        path = _latest_project_path()
                        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                        _log_activity(f"Sesión guardada: {path}", "OK")
                        ctx.refresh_header_status()
                    except Exception as exc:
                        _log_activity(f"No se pudo guardar sesión: {exc}", "WARN")

                def load_project_click() -> None:
                    try:
                        path = _latest_project_path()
                        payload = json.loads(path.read_text(encoding="utf-8"))
                        state.suppress_setup_dirty = True
                        ctx.platform_select.set_value(payload.get("platform", _current_platform().value))
                        source.value = payload.get("source") or ""
                        dat.value = payload.get("dat") or ""
                        outdir.value = payload.get("outdir") or ""
                        arcade_mode.value = payload.get("arcade_mode") or "auto"
                        profile_payload = payload.get("profile")
                        if profile_payload and ctx.controls and "profile_name" in ctx.controls:
                            profile = SelectionProfile.model_validate(profile_payload)
                            state.profile = profile
                            _apply_profile_to_controls(profile, ctx.controls)
                        _log_activity(f"Sesión cargada: {path}", "OK")
                        ctx.refresh_needed_table()
                        ctx.refresh_header_status()
                        ctx.set_setup_ready(False)
                    except Exception as exc:
                        _log_activity(f"No se pudo cargar sesión: {exc}", "WARN")
                    finally:
                        state.suppress_setup_dirty = False
                with ui.row().classes("items-center"):
                    ui.button("Guardar sesión", icon="save", on_click=save_project_click).props("outline")
                    ui.button("Cargar sesión", icon="folder_open", on_click=load_project_click).props("outline")

            with ui.column().classes(_panel_class()):
                ui.label("DAT de referencia").classes("text-lg font-semibold")
                dat = ui.input("Archivo DAT/XML/ZIP").props("outlined readonly").classes("w-full")
                ctx.header_refs["dat"] = dat
                dat_dialog = _path_picker(dat, choose="file", suffixes={".dat", ".xml", ".zip"})
                def setup_value_changed() -> None:
                    ctx.mark_setup_dirty()
                    ctx.refresh_needed_table()

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
                    ctx.refresh_needed_table()

                ui.button("Sugerir DAT según romset", icon="auto_awesome", on_click=suggest_dat_click).props("outline").classes("w-fit")
                source_options = {item.id: item.label for item in list_dat_sources(_current_platform().value)}
                dat_source = ui.select(source_options, value=next(iter(source_options)), label="Descargar DAT").props("outlined").classes("w-full")

                async def download_dat_click() -> None:
                    try:
                        imported = await asyncio.to_thread(download_and_import_source, dat_source.value)
                        dat.value = imported[0].path
                        dat_status.text = f"DAT descargado e importado: {imported[0].name}"
                        ctx.refresh_dat_table()
                        ctx.refresh_needed_table()
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
                    ctx.set_setup_ready(ready)
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
                    with busy("sincronización de hashes RetroAchievements"):
                        count = await asyncio.to_thread(sync_ra_hashes, platform, username.value, api_key.value)
                    ra_status.text = f"Listo: {count} hashes RA cacheados."
                    ra_cache_status.text = _ra_status_label(platform)
                    ctx.refresh_header_status()
                except Exception as exc:
                    ra_status.text = f"Error RA: {exc}"

            async def sync_ra_details_click() -> None:
                try:
                    platform = _current_platform()
                    state.ra_details_progress = {"current": 0, "total": int(details_limit.value or 150), "updated": 0, "running": True}
                    ra_status.text = "Sincronizando detalles RA: labels, nombres de hash y PatchUrl..."
                    def progress_update(update: dict[str, int]) -> None:
                        state.ra_details_progress = {**update, "running": True}

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
                    current_progress = state.ra_details_progress
                    total = int(current_progress.get("total", 0) or 0)
                    state.ra_details_progress = {"current": total, "total": total, "updated": count, "running": False}
                    scan_result = state.scan
                    if scan_result is not None:
                        state.scan = await asyncio.to_thread(annotate_scan_with_ra, scan_result)
                    ra_status.text = f"Detalles RA actualizados: {count}. Puedes continuar luego; se priorizan pendientes. 🩹 indica hash con parche localizado."
                    _log_activity(f"Detalles RA actualizados para {platform_spec(platform).short_name}: {count}", "OK")
                    ra_cache_status.text = _ra_status_label(platform)
                    ctx.refresh_coverage()
                    ctx.refresh_decisions()
                except Exception as exc:
                    current = state.ra_details_progress
                    state.ra_details_progress = {**current, "running": False}
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
                progress = state.ra_details_progress
                current = int(progress.get("current", 0) or 0)
                total = int(progress.get("total", 0) or 0)
                updated = int(progress.get("updated", 0) or 0)
                value = current / total if total else 0
                ra_details_progress.value = value
                percent = round(value * 100)
                ra_details_progress_label.text = f"Detalles RA: {percent}% · {current} / {total} juegos · {updated} hashes actualizados"

            ui.timer(0.3, refresh_ra_details_progress)

    ctx.source = source
    ctx.outdir = outdir
    ctx.arcade_mode = arcade_mode
    ctx.dat = dat
    ctx.dat_status = dat_status
    ctx.dat_source = dat_source
    ctx.ra_cache_status = ra_cache_status
    ctx.refresh_setup_platform_summary = refresh_setup_platform_summary
