from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .dat import DatIndex, parse_dat
from .dat_manager import compare_dats, download_and_import_source, download_and_import_url, import_dat_file, list_installed_dats, validate_setup
from .dat_sources import list_dat_sources
from .download_plan import build_download_plan, human_size, resolve_remote_files
from .downloader import run_download_plan
from .manifest_io import apply_manifest, load_manifest, report_manifest, save_manifest
from .models import ActionMode, ExportLayout, OutputBucket, Platform
from .paths import project_state_dir
from .platforms import platform_options, platform_spec
from .profile import load_profile
from .ra import annotate_scan_with_ra, sync_ra_hashes, sync_ra_patch_details
from .rom_sources import SOURCE_KIND_LABELS, RomSource, add_rom_source, list_rom_sources, remove_rom_source, set_rom_source_enabled
from .rules import build_manifest
from .scanner import scan_directory
from .storage import load_scan, save_scan

app = typer.Typer(help="Herramientas RetroPerfect para curar colecciones de ROMs.")
console = Console()


def _platform(value: str) -> Platform:
    try:
        return Platform(value)
    except ValueError as exc:
        supported = ", ".join(platform_options())
        raise typer.BadParameter(f"Plataforma no soportada '{value}'. Soportadas: {supported}.") from exc


@app.command()
def scan(
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    input: Annotated[Path, typer.Option("--input", exists=True, file_okay=True, dir_okay=True, readable=True)] = Path("."),
    dat: Annotated[Path | None, typer.Option("--dat", exists=True, file_okay=True, dir_okay=False, readable=True)] = None,
    annotate_ra: Annotated[bool, typer.Option("--annotate-ra/--no-annotate-ra")] = True,
    hash_cache: Annotated[bool, typer.Option("--hash-cache/--no-hash-cache", help="Reutiliza hashes de escaneos anteriores si el archivo no cambió.")] = True,
    workers: Annotated[int | None, typer.Option("--workers", min=1, help="Hilos de hashing en paralelo (por defecto, hasta 8 según CPUs).")] = None,
) -> None:
    """Escanea ROMs sueltas y contenedores ZIP/7z de una plataforma."""
    parsed_platform = _platform(platform)
    dat_path = dat
    if dat_path and dat_path.suffix.lower() == ".zip":
        imported = import_dat_file(dat_path)
        dat_path = Path(imported[0].path)
    dat_index = DatIndex(parse_dat(dat_path)) if dat_path else None
    cache_path = project_state_dir() / "scan-cache.sqlite3" if hash_cache else None
    result = scan_directory(input, parsed_platform, dat_index=dat_index, dat_path=dat_path, hash_cache=cache_path, workers=workers)
    if annotate_ra:
        result = annotate_scan_with_ra(result)
    path = save_scan(result)
    table = Table(title="Scan Summary")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Scan ID", result.id)
    table.add_row("Platform", platform_spec(result.platform).short_name)
    table.add_row("ROM candidates", str(len(result.roms)))
    table.add_row("Unmatched files", str(len(result.unmatched_files)))
    table.add_row("Saved", str(path))
    console.print(table)


@app.command("sync-ra")
def sync_ra(
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    username: Annotated[str | None, typer.Option("--username")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    details: Annotated[bool, typer.Option("--details/--no-details")] = False,
    details_limit: Annotated[int | None, typer.Option("--details-limit")] = None,
) -> None:
    """Sincroniza la caché de hashes RetroAchievements de una plataforma."""
    parsed_platform = _platform(platform)
    count = sync_ra_hashes(parsed_platform, username=username, api_key=api_key)
    console.print(f"[green]Cached {count} RetroAchievements hashes.[/green]")
    if details:
        detailed = sync_ra_patch_details(parsed_platform, username=username, api_key=api_key, limit=details_limit)
        console.print(f"[green]Updated {detailed} RetroAchievements hash details/patch labels.[/green]")


@app.command("sync-ra-details")
def sync_ra_details(
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    username: Annotated[str | None, typer.Option("--username")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    limit: Annotated[int | None, typer.Option("--limit")] = None,
) -> None:
    """Sincroniza metadatos RA Supported Game Files, incluidos labels y URLs de parches."""
    count = sync_ra_patch_details(_platform(platform), username=username, api_key=api_key, limit=limit)
    console.print(f"[green]Updated {count} RetroAchievements hash details/patch labels.[/green]")


@app.command()
def plan(
    scan: Annotated[Path, typer.Option("--scan", exists=True, file_okay=True, dir_okay=False, readable=True)],
    profile: Annotated[str, typer.Option("--profile")] = "default",
    outputs: Annotated[str, typer.Option("--outputs")] = "main,ra",
    output_dir: Annotated[Path | None, typer.Option("--output-dir")] = None,
    action: Annotated[ActionMode, typer.Option("--action")] = ActionMode.COPY,
    layout: Annotated[ExportLayout | None, typer.Option("--layout")] = None,
    auto_patch_ra: Annotated[bool | None, typer.Option("--auto-patch-ra/--no-auto-patch-ra")] = None,
    manifest_out: Annotated[Path, typer.Option("--manifest-out")] = Path(".retroperfect/manifests/latest.json"),
) -> None:
    """Crea un manifiesto de previsualización a partir de un escaneo y un perfil."""
    scan_result = load_scan(scan)
    selected_outputs = [OutputBucket(item.strip()) for item in outputs.split(",") if item.strip()]
    selection_profile = load_profile(profile)
    if layout is not None:
        selection_profile = selection_profile.model_copy(update={"export_layout": layout})
    if auto_patch_ra is not None:
        selection_profile = selection_profile.model_copy(update={"auto_patch_ra": auto_patch_ra})
    manifest = build_manifest(scan_result, selection_profile, selected_outputs, output_dir=output_dir, action=action)
    path = save_manifest(manifest, manifest_out)
    table = Table(title="Plan Summary")
    table.add_column("Bucket")
    table.add_column("Source")
    table.add_column("Destination")
    table.add_column("Reason")
    for entry in manifest.entries:
        table.add_row(entry.bucket.value, entry.source_path, entry.destination_path or "", " | ".join(entry.explanation))
    console.print(table)
    console.print(f"[green]Manifest saved to {path}[/green]")


@app.command()
def apply(
    manifest: Annotated[Path, typer.Option("--manifest", exists=True, file_okay=True, dir_okay=False, readable=True)],
    mode: Annotated[ActionMode | None, typer.Option("--mode", help="Guarda de seguridad: debe coincidir con la acción planificada en el manifiesto.")] = None,
    confirm: Annotated[bool, typer.Option("--confirm/--no-confirm")] = False,
    verify: Annotated[bool, typer.Option("--verify/--no-verify", help="Verifica por MD5 cada archivo copiado/movido/parcheado.")] = True,
    hard_delete: Annotated[bool, typer.Option("--hard-delete", help="Borra definitivamente en vez de mover a .retroperfect/trash.")] = False,
) -> None:
    """Aplica un manifiesto guardado usando la acción planificada de cada entrada. Requiere --confirm."""
    loaded = load_manifest(manifest)
    completed = apply_manifest(loaded, mode=mode, confirm=confirm, verify=verify, hard_delete=hard_delete)
    for line in completed:
        console.print(line)


@app.command()
def report(
    manifest: Annotated[Path, typer.Option("--manifest", exists=True, file_okay=True, dir_okay=False, readable=True)],
    format: Annotated[str, typer.Option("--format")] = "html",
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Genera un reporte a partir de un manifiesto."""
    loaded = load_manifest(manifest)
    output_path = output or Path(f".retroperfect/reports/{loaded.id}.{format}")
    report_manifest(loaded, output_path, format)
    console.print(f"[green]Report saved to {output_path}[/green]")


@app.command()
def verify(
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    input: Annotated[Path, typer.Option("--input", exists=True, file_okay=True, dir_okay=True, readable=True)] = Path("."),
    dat: Annotated[Path, typer.Option("--dat", exists=True, file_okay=True, dir_okay=False, readable=True)] = ...,  # type: ignore[assignment]
    workers: Annotated[int | None, typer.Option("--workers", min=1)] = None,
    limit: Annotated[int, typer.Option("--limit", help="Máximo de incidencias a listar.")] = 50,
    format: Annotated[str, typer.Option("--format", help="Formato del informe: table, json, csv o html.")] = "table",
    output: Annotated[Path | None, typer.Option("--output", help="Ruta del informe (por defecto .retroperfect/reports/verify.<ext>).")] = None,
) -> None:
    """Verifica la colección contra un DAT: faltantes, sobrantes, mal nombrados y duplicados."""
    from .verify import report_verify, verify_collection

    parsed_platform = _platform(platform)
    catalog = parse_dat(dat)
    cache_path = project_state_dir() / "scan-cache.sqlite3"
    scan_result = scan_directory(input, parsed_platform, dat_index=DatIndex(catalog), dat_path=dat, hash_cache=cache_path, workers=workers)
    report = verify_collection(scan_result, catalog)

    if format != "table":
        report_path = output or Path(f".retroperfect/reports/verify.{format}")
        report_verify(report, report_path, format)
        console.print(f"[green]Informe de verificación guardado en {report_path}[/green]")
        if not report.clean:
            raise typer.Exit(code=1)
        return

    summary = Table(title="Verificación de colección")
    summary.add_column("Métrica")
    summary.add_column("Valor", justify="right")
    summary.add_row("Juegos en el DAT", str(report.dat_games))
    summary.add_row("Juegos en el romset", str(report.romset_games))
    summary.add_row("Coincidentes", str(report.matched_games))
    summary.add_row("Faltantes", str(report.missing))
    summary.add_row("Fuera del DAT", str(report.unmatched))
    summary.add_row("Mal nombrados", str(report.misnamed))
    summary.add_row("Duplicados", str(report.duplicates))
    console.print(summary)

    if report.clean:
        console.print("[green]Colección verificada: sin incidencias respecto al DAT.[/green]")
        return
    detail = Table(title=f"Incidencias ({min(len(report.issues), limit)} de {len(report.issues)})")
    detail.add_column("Estado")
    detail.add_column("Juego")
    detail.add_column("Detalle")
    for issue in report.issues[:limit]:
        detail.add_row(issue.status, issue.title, issue.detail)
    console.print(detail)
    raise typer.Exit(code=1)


@app.command("dat-import")
def dat_import(path: Annotated[Path, typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True)]) -> None:
    """Importa un .dat/.xml/.zip de DAT-o-MATIC en la biblioteca local de DATs."""
    imported = import_dat_file(path)
    for dat in imported:
        console.print(f"[green]Imported[/green] {dat.name} ({dat.format}, {dat.header_mode}, games={dat.games}, roms={dat.roms}, recommended={dat.recommended})")


@app.command("dat-download")
def dat_download(
    source: Annotated[str | None, typer.Option("--source")] = None,
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    url: Annotated[str | None, typer.Option("--url")] = None,
    filename: Annotated[str | None, typer.Option("--filename")] = None,
) -> None:
    """Descarga e importa una fuente DAT online o una URL directa DAT/XML/ZIP."""
    if not source and not url:
        parsed_platform = _platform(platform)
        table = Table(title="Online DAT Sources")
        for column in ["ID", "Label", "Format", "Direct", "URL"]:
            table.add_column(column)
        for item in list_dat_sources(parsed_platform.value):
            table.add_row(item.id, item.label, item.format, "yes" if item.direct_download else "no", item.url)
        console.print(table)
        return
    imported = download_and_import_source(source) if source else download_and_import_url(url or "", filename=filename)
    for dat in imported:
        console.print(f"[green]Downloaded[/green] {dat.name} ({dat.format}, {dat.header_mode}, games={dat.games}, roms={dat.roms}, recommended={dat.recommended})")


@app.command("dat-update")
def dat_update(
    platform: Annotated[str | None, typer.Option("--platform", help="Limita la actualización a una plataforma.")] = None,
) -> None:
    """Re-descarga los DATs instalados de fuentes directas y reporta cambios. Ideal para cron."""
    from .dat_manager import update_installed_dats

    results = update_installed_dats(_platform(platform) if platform else None)
    if not results:
        console.print("No hay DATs instalados de fuentes con descarga directa. Los importados a mano se actualizan re-importándolos.")
        return
    table = Table(title="Actualización de DATs")
    for column in ["Nombre", "Plataforma", "Estado", "Detalle"]:
        table.add_column(column)
    for result in results:
        color = {"actualizado": "green", "sin cambios": "blue", "error": "red"}.get(result.status, "white")
        table.add_row(result.name, result.platform or "", f"[{color}]{result.status}[/{color}]", result.detail)
    console.print(table)
    if any(result.status == "error" for result in results):
        raise typer.Exit(code=1)


@app.command("rom-sources")
def rom_sources() -> None:
    """Lista las fuentes de romsets configuradas. RetroPerfect no trae ninguna: las añades tú."""
    sources = list_rom_sources()
    if not sources:
        console.print("No hay fuentes configuradas. Añade una con [bold]rom-source-add[/bold]:")
        for kind, label in SOURCE_KIND_LABELS.items():
            console.print(f"  · [cyan]{kind}[/cyan] — {label}")
        return
    table = Table(title="Fuentes de romsets")
    for column in ["ID", "Etiqueta", "Tipo", "Origen", "Plataforma", "Activa"]:
        table.add_column(column)
    for source in sources:
        table.add_row(source.id, source.label, source.kind, source.location, source.platform or "todas", "sí" if source.enabled else "no")
    console.print(table)


@app.command("rom-source-add")
def rom_source_add(
    id: Annotated[str, typer.Option("--id", help="Identificador corto y único.")],
    label: Annotated[str, typer.Option("--label", help="Nombre visible de la fuente.")],
    kind: Annotated[str, typer.Option("--kind", help="archive_org, http_index o local_dir.")],
    location: Annotated[str, typer.Option("--location", help="Ítem de archive.org, URL del índice o ruta de la carpeta.")],
    platform: Annotated[str | None, typer.Option("--platform", help="Limita la fuente a una plataforma.")] = None,
    notes: Annotated[str, typer.Option("--notes")] = "",
) -> None:
    """Registra una fuente de descarga. Tú eliges el origen y respondes de su contenido."""
    if kind not in SOURCE_KIND_LABELS:
        raise typer.BadParameter(f"Tipo no soportado '{kind}'. Soportados: {', '.join(SOURCE_KIND_LABELS)}.")
    parsed_platform = _platform(platform).value if platform else None
    source = add_rom_source(RomSource(id=id, label=label, kind=kind, location=location, platform=parsed_platform, notes=notes))  # type: ignore[arg-type]
    console.print(f"[green]Fuente añadida[/green] {source.label} ({source.kind} → {source.location})")


@app.command("rom-source-toggle")
def rom_source_toggle(
    source_id: Annotated[str, typer.Argument(help="ID de la fuente (ver rom-sources).")],
    enable: Annotated[bool, typer.Option("--enable/--disable", help="Silencia la fuente sin borrarla.")] = True,
) -> None:
    """Activa o desactiva una fuente, útil cuando un espejo está caído."""
    try:
        source = set_rom_source_enabled(source_id, enable)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"[green]{'Activada' if source.enabled else 'Desactivada'}[/green] {source.label}")


@app.command("rom-source-remove")
def rom_source_remove(source_id: Annotated[str, typer.Argument(help="ID de la fuente (ver rom-sources).")]) -> None:
    """Elimina una fuente de romsets y su índice cacheado."""
    if not remove_rom_source(source_id):
        console.print(f"[yellow]No existe ninguna fuente con ID '{source_id}'.[/yellow]")
        raise typer.Exit(code=1)
    console.print(f"[green]Fuente eliminada:[/green] {source_id}")


@app.command()
def download(
    dat: Annotated[Path, typer.Option("--dat", exists=True, file_okay=True, dir_okay=False, readable=True, help="DAT que define qué debería tener la colección.")],
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    scan: Annotated[Path | None, typer.Option("--scan", exists=True, file_okay=True, dir_okay=False, readable=True, help="Escaneo previo; sin él se considera que no tienes nada.")] = None,
    dest: Annotated[Path | None, typer.Option("--dest", help="Carpeta donde instalar lo descargado y verificado.")] = None,
    profile: Annotated[str, typer.Option("--profile")] = "default",
    source: Annotated[str | None, typer.Option("--source", help="Limita a una fuente concreta.")] = None,
    all_variants: Annotated[bool, typer.Option("--all-variants/--profile-filter", help="Sin filtro de perfil, todas las variantes del DAT.")] = False,
    refresh: Annotated[bool, typer.Option("--refresh/--no-refresh", help="Fuerza releer el índice de las fuentes.")] = False,
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="Descarga como mucho N archivos.")] = None,
    confirm: Annotated[bool, typer.Option("--confirm/--no-confirm", help="Sin --confirm solo se muestra el plan.")] = False,
) -> None:
    """Descarga de tus fuentes solo lo que falta según el DAT y el perfil, verificándolo antes de instalarlo."""
    parsed_platform = _platform(platform)
    sources = [item for item in list_rom_sources(parsed_platform.value) if source is None or item.id == source]
    if not sources:
        console.print("[yellow]No hay fuentes configuradas para esta plataforma.[/yellow] Añade una con rom-source-add.")
        raise typer.Exit(code=1)

    catalog = parse_dat(dat)
    scan_result = load_scan(scan) if scan else None
    remote_files, errors = resolve_remote_files(sources, refresh=refresh)
    for message in errors:
        console.print(f"[red]Fuente no disponible:[/red] {message}")
    if not remote_files:
        if not errors:
            console.print("[yellow]Todas las fuentes de esta plataforma están desactivadas.[/yellow] Actívalas con rom-source-toggle.")
        raise typer.Exit(code=1)

    plan = build_download_plan(
        catalog,
        scan_result,
        load_profile(profile),
        remote_files,
        platform=parsed_platform,
        apply_profile=not all_variants,
    )
    if limit:
        plan.candidates = plan.candidates[:limit]

    table = Table(title=f"Plan de descarga · {platform_spec(parsed_platform).short_name}")
    for column in ["Juego", "Archivo", "Tamaño", "Confianza"]:
        table.add_column(column)
    for candidate in plan.candidates:
        table.add_row(candidate.title, candidate.file_name, human_size(candidate.size), candidate.confidence)
    console.print(table)
    console.print(
        f"Grupos en el DAT: {plan.dat_groups} · ya presentes: {plan.present_groups} · descartados por perfil: {plan.filtered_by_profile} "
        f"· a descargar: {len(plan.candidates)} ({human_size(plan.total_bytes)}) · sin fuente: {len(plan.unavailable)}"
    )

    if not plan.candidates:
        return
    if not confirm:
        console.print("[yellow]Simulación:[/yellow] repite con --confirm --dest <carpeta> para descargar.")
        return
    if dest is None:
        raise typer.BadParameter("--dest es obligatorio para descargar de verdad.")

    report = run_download_plan(plan, dest, dat_index=DatIndex(catalog))
    for outcome in report.outcomes:
        color = {"ok": "green", "present": "blue", "mismatch": "red", "error": "red", "cancelled": "yellow"}.get(outcome.status, "white")
        console.print(f"[{color}]{outcome.status_label}[/{color}] {outcome.file_name} {outcome.detail}")
    console.print(f"Descargados {report.downloaded}, con problemas {report.failed}, total {human_size(report.total_bytes)}.")
    if report.failed:
        raise typer.Exit(code=1)


@app.command("dat-list")
def dat_list() -> None:
    """Lista los DATs instalados."""
    table = Table(title="Installed DATs")
    for column in ["Name", "Source", "Format", "Header", "Recommended", "Games", "ROMs", "P/C", "Path"]:
        table.add_column(column)
    for dat in list_installed_dats():
        table.add_row(dat.name, dat.source, dat.format, dat.header_mode, "yes" if dat.recommended else "no", str(dat.games), str(dat.roms), "yes" if dat.parent_clone else "no", dat.path)
    console.print(table)


@app.command("dat-compare")
def dat_compare(
    left: Annotated[Path, typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True)],
    right: Annotated[Path, typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True)],
) -> None:
    """Compara dos DATs por grupos de juegos y hashes de ROMs."""
    comparison = compare_dats(left, right)
    table = Table(title=f"{comparison.left_name} vs {comparison.right_name}")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("Common games", str(comparison.common_games))
    table.add_row("Left-only games", str(comparison.left_only_games))
    table.add_row("Right-only games", str(comparison.right_only_games))
    table.add_row("Common ROMs", str(comparison.common_roms))
    table.add_row("Left-only ROMs", str(comparison.left_only_roms))
    table.add_row("Right-only ROMs", str(comparison.right_only_roms))
    console.print(table)


@app.command("validate")
def validate(
    input: Annotated[Path | None, typer.Option("--input", exists=False)] = None,
    dat: Annotated[Path | None, typer.Option("--dat", exists=False)] = None,
    output_dir: Annotated[Path | None, typer.Option("--output-dir", exists=False)] = None,
) -> None:
    """Valida origen, DAT y salida antes de escanear."""
    issues = validate_setup(input, dat, output_dir)
    if not issues:
        console.print("[green]Configuration looks ready.[/green]")
        return
    for issue in issues:
        console.print(f"[yellow]- {issue}[/yellow]")


@app.command("trash-list")
def trash_list() -> None:
    """Lista las sesiones de la papelera del proyecto."""
    from .trash import list_sessions

    sessions = list_sessions()
    if not sessions:
        console.print("La papelera está vacía.")
        return
    table = Table(title="Papelera (.retroperfect/trash)")
    for column in ["Sesión", "Creada", "Archivos", "Tamaño", "Restaurable"]:
        table.add_column(column)
    for session in sessions:
        table.add_row(session.name, session.created, str(session.files), f"{session.total_size / (1024 * 1024):.1f} MB", "sí" if session.restorable else "no")
    console.print(table)


@app.command("trash-restore")
def trash_restore(session: Annotated[str, typer.Argument(help="Nombre de la sesión (ver trash-list).")]) -> None:
    """Restaura los archivos de una sesión de papelera a sus rutas originales."""
    from .trash import restore_session

    for line in restore_session(session):
        console.print(line)


@app.command("trash-empty")
def trash_empty(confirm: Annotated[bool, typer.Option("--confirm/--no-confirm")] = False) -> None:
    """Vacía la papelera de forma definitiva. Requiere --confirm."""
    from .trash import empty_trash

    if not confirm:
        console.print("[yellow]Vaciar la papelera es irreversible. Repite con --confirm.[/yellow]")
        raise typer.Exit(code=1)
    removed = empty_trash()
    console.print(f"[green]Papelera vaciada: {removed} archivos eliminados definitivamente.[/green]")


@app.command()
def gui(
    host: str = "127.0.0.1",
    port: int = 8080,
    exit_on_idle: Annotated[bool, typer.Option("--exit-on-idle/--no-exit-on-idle", help="Cierra la aplicación cuando no queda ningún navegador conectado.")] = False,
) -> None:
    """Arranca la interfaz local NiceGUI."""
    from .gui import run

    run(host=host, port=port, exit_on_idle=exit_on_idle)


if __name__ == "__main__":
    app()
