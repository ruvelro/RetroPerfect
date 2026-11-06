from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .dat import DatIndex, parse_dat
from .dat_manager import compare_dats, download_and_import_source, download_and_import_url, import_dat_file, list_installed_dats, validate_setup
from .dat_sources import list_dat_sources
from .download_plan import build_download_plan, human_size, resolve_remote_files
from .downloader import collect_downloads, run_download_plan
from .manifest_io import REPORT_FORMATS, apply_manifest, load_manifest, report_manifest, save_manifest
from .models import ActionMode, ContainerMode, DatCatalog, ExportLayout, OutputBucket, Platform, SelectionProfile
from .paths import project_state_dir
from .platforms import platform_options, platform_spec
from .profile import load_profile
from .ra import annotate_scan_with_ra, sync_ra_hashes, sync_ra_patch_details
from .rom_sources import SOURCE_KIND_LABELS, RomSource, add_rom_source, list_rom_sources, remove_rom_source, set_rom_source_enabled
from .rules import build_manifest
from .scanner import scan_directory
from .storage import load_scan, save_scan
from .torrent import read_torrent
from .torrent_client import DEFAULT_URL as QBT_DEFAULT_URL
from .torrent_client import QBittorrentClient, TorrentClientError, queue_plan

app = typer.Typer(help="Herramientas RetroPerfect para curar colecciones de ROMs.")
console = Console()


def _print_version(value: bool) -> None:
    if value:
        console.print(f"RetroPerfect {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[bool, typer.Option("--version", callback=_print_version, is_eager=True, help="Muestra la versión y sale.")] = False,
) -> None:
    """Curación de colecciones de ROMs verificada contra DATs oficiales."""


def _platform(value: str) -> Platform:
    try:
        return Platform(value)
    except ValueError as exc:
        supported = ", ".join(platform_options())
        raise typer.BadParameter(f"Plataforma no soportada '{value}'. Soportadas: {supported}.") from exc


def _catalog(path: Path) -> DatCatalog:
    """Lee un DAT y convierte un archivo inservible en un aviso, no en un traceback.

    Un DAT puede estar corrupto, no ser XML o declarar entidades propias (que se
    rechazan por seguridad): nada de eso es un fallo del programa.
    """
    try:
        return parse_dat(path)
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--dat") from exc


def _profile(value: str) -> SelectionProfile:
    """Perfil por nombre o por ruta, con el error como aviso de parámetro."""
    try:
        return load_profile(value)
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--profile") from exc


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
    dat_index = DatIndex(_catalog(dat_path)) if dat_path else None
    cache_path = project_state_dir() / "scan-cache.sqlite3" if hash_cache else None
    result = scan_directory(input, parsed_platform, dat_index=dat_index, dat_path=dat_path, hash_cache=cache_path, workers=workers)
    if annotate_ra:
        result = annotate_scan_with_ra(result)
    path = save_scan(result)
    table = Table(title="Resumen del escaneo")
    table.add_column("Métrica")
    table.add_column("Valor")
    table.add_row("ID del escaneo", result.id)
    table.add_row("Plataforma", platform_spec(result.platform).short_name)
    table.add_row("Candidatos a ROM", str(len(result.roms)))
    table.add_row("Archivos no reconocidos", str(len(result.unmatched_files)))
    table.add_row("Guardado en", str(path))
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
    console.print(f"[green]Cacheados {count} hashes de RetroAchievements.[/green]")
    if details:
        detailed = sync_ra_patch_details(parsed_platform, username=username, api_key=api_key, limit=details_limit)
        console.print(f"[green]Actualizados {detailed} detalles de hash y etiquetas de parche de RetroAchievements.[/green]")


@app.command("sync-ra-details")
def sync_ra_details(
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    username: Annotated[str | None, typer.Option("--username")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    limit: Annotated[int | None, typer.Option("--limit")] = None,
) -> None:
    """Sincroniza metadatos RA Supported Game Files, incluidos labels y URLs de parches."""
    count = sync_ra_patch_details(_platform(platform), username=username, api_key=api_key, limit=limit)
    console.print(f"[green]Actualizados {count} detalles de hash y etiquetas de parche de RetroAchievements.[/green]")


@app.command()
def plan(
    scan: Annotated[Path, typer.Option("--scan", exists=True, file_okay=True, dir_okay=False, readable=True)],
    profile: Annotated[str, typer.Option("--profile", help="Nombre de un perfil (`default`, uno recomendado o uno guardado) o ruta de un .yaml/.json.")] = "default",
    outputs: Annotated[str, typer.Option("--outputs")] = "main,ra",
    output_dir: Annotated[Path | None, typer.Option("--output-dir")] = None,
    action: Annotated[ActionMode, typer.Option("--action")] = ActionMode.COPY,
    layout: Annotated[ExportLayout | None, typer.Option("--layout")] = None,
    containers: Annotated[ContainerMode, typer.Option("--containers", help="Qué hacer con los ZIP/7z: keep copia el contenedor entero, extract saca la ROM suelta, rezip crea un ZIP por juego con solo lo que se conserva y torrentzip lo hace de forma canónica (mismos bytes para el mismo contenido).")] = ContainerMode.KEEP,
    auto_patch_ra: Annotated[bool | None, typer.Option("--auto-patch-ra/--no-auto-patch-ra")] = None,
    manifest_out: Annotated[Path | None, typer.Option("--manifest-out", help="Por defecto <carpeta del proyecto>/.retroperfect/manifests/latest.json.")] = None,
) -> None:
    """Crea un manifiesto de previsualización a partir de un escaneo y un perfil."""
    scan_result = load_scan(scan)
    selected_outputs = [OutputBucket(item.strip()) for item in outputs.split(",") if item.strip()]
    selection_profile = _profile(profile)
    if layout is not None:
        selection_profile = selection_profile.model_copy(update={"export_layout": layout})
    if auto_patch_ra is not None:
        selection_profile = selection_profile.model_copy(update={"auto_patch_ra": auto_patch_ra})
    manifest = build_manifest(scan_result, selection_profile, selected_outputs, output_dir=output_dir, action=action, container_mode=containers)
    path = save_manifest(manifest, manifest_out or project_state_dir() / "manifests" / "latest.json")
    table = Table(title="Resumen del plan")
    table.add_column("Salida")
    table.add_column("Origen")
    table.add_column("Destino")
    table.add_column("Motivo")
    for entry in manifest.entries:
        table.add_row(entry.bucket.value, entry.source_path, entry.destination_path or "", " | ".join(entry.explanation))
    console.print(table)
    if manifest.archives:
        console.print(f"Se crearán {len(manifest.archives)} ZIP con solo los archivos que se conservan.")
    console.print(f"[green]Manifiesto guardado en {path}[/green]")


@app.command()
def apply(
    manifest: Annotated[Path, typer.Option("--manifest", exists=True, file_okay=True, dir_okay=False, readable=True)],
    mode: Annotated[ActionMode | None, typer.Option("--mode", help="Guarda de seguridad: debe coincidir con la acción planificada en el manifiesto.")] = None,
    confirm: Annotated[bool, typer.Option("--confirm/--no-confirm")] = False,
    verify: Annotated[bool, typer.Option("--verify/--no-verify", help="Verifica por MD5 cada archivo copiado/movido/parcheado.")] = True,
    hard_delete: Annotated[bool, typer.Option("--hard-delete", help="Borra definitivamente en vez de mover a .retroperfect/trash.")] = False,
    link: Annotated[bool, typer.Option("--link", help="Enlaza en vez de copiar cuando origen y destino están en el mismo disco: no ocupa espacio extra.")] = False,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Reemplaza los archivos del destino que ya existan con otro contenido. Sin esto, la aplicación se detiene y no toca nada.")] = False,
) -> None:
    """Aplica un manifiesto guardado usando la acción planificada de cada entrada. Requiere --confirm."""
    loaded = load_manifest(manifest)
    if not confirm:
        console.print(f"[yellow]Aplicar toca tus archivos: {len(loaded.entries)} operaciones en el manifiesto. Revísalo y repite con --confirm.[/yellow]")
        raise typer.Exit(code=1)
    try:
        completed = apply_manifest(loaded, mode=mode, confirm=confirm, verify=verify, hard_delete=hard_delete, link=link, overwrite=overwrite)
    except (RuntimeError, OSError) as exc:
        # Preflight, modo incompatible, destino ocupado u origen cambiado desde
        # el escaneo: son avisos para el usuario, no fallos del programa. Si
        # salta en pleno copiado, lo aplicado hasta ahí queda en el journal; un
        # error del sistema de archivos tampoco debe salir como traceback.
        console.print(f"[red]No se aplicó el manifiesto:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    for line in completed:
        console.print(line)


@app.command()
def report(
    manifest: Annotated[Path, typer.Option("--manifest", exists=True, file_okay=True, dir_okay=False, readable=True)],
    format: Annotated[str, typer.Option("--format")] = "html",
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Genera un reporte a partir de un manifiesto."""
    if format not in REPORT_FORMATS:
        raise typer.BadParameter(f"Formato desconocido '{format}'. Usa uno de: {', '.join(sorted(REPORT_FORMATS))}.", param_hint="--format")
    loaded = load_manifest(manifest)
    output_path = output or project_state_dir() / "reports" / f"{loaded.id}.{format}"
    report_manifest(loaded, output_path, format)
    console.print(f"[green]Informe guardado en {output_path}[/green]")


@app.command()
def audit(
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    input: Annotated[Path, typer.Option("--input", exists=True, file_okay=True, dir_okay=True, readable=True)] = Path("."),
    dat: Annotated[Path | None, typer.Option("--dat", exists=True, file_okay=True, dir_okay=False, readable=True)] = None,
    scan: Annotated[Path | None, typer.Option("--scan", exists=True, file_okay=True, dir_okay=False, readable=True, help="Reutiliza un escaneo guardado en vez de volver a escanear.")] = None,
    manifest: Annotated[Path | None, typer.Option("--manifest", exists=True, file_okay=True, dir_okay=False, readable=True)] = None,
    workers: Annotated[int | None, typer.Option("--workers", min=1)] = None,
) -> None:
    """Nota de salud de la colección, con la cobertura y los avisos de la pestaña Resumen."""
    from .coverage import build_coverage
    from .diagnostics import build_patch_queue, build_perfect_audit, detect_dat_warnings

    parsed_platform = _platform(platform)
    catalog = _catalog(dat) if dat else None
    if scan:
        scan_result = load_scan(scan)
    else:
        cache_path = project_state_dir() / "scan-cache.sqlite3"
        scan_result = scan_directory(input, parsed_platform, dat_index=DatIndex(catalog) if catalog else None, dat_path=dat, hash_cache=cache_path, workers=workers)
    loaded_manifest = load_manifest(manifest) if manifest else None
    coverage = build_coverage(scan_result, catalog, loaded_manifest)
    summary = build_perfect_audit(coverage, scan_result, loaded_manifest)

    console.print(f"[bold]Nota: {summary.score}/100[/bold] · {summary.verdict}")
    table = Table(title="Auditoría de la colección")
    table.add_column("Métrica")
    table.add_column("Valor", justify="right")
    for label, value in [
        ("Juegos completos", summary.complete_games),
        ("Faltantes", summary.missing_games),
        ("Fuera del DAT", summary.unmatched_games),
        ("Grupos duplicados", summary.duplicate_groups),
        ("Con RetroAchievements", summary.ra_covered_games),
        ("Sin RetroAchievements", summary.ra_missing_games),
        ("Parches pendientes", summary.patch_pending),
    ]:
        table.add_row(label, str(value))
    console.print(table)
    for note in summary.notes:
        console.print(f"  · {note}")

    warnings = detect_dat_warnings(parsed_platform, input, dat, scan_result)
    if warnings:
        console.print("\n[bold]Avisos[/bold]")
        for row in warnings:
            color = {"OK": "green", "WARN": "yellow", "MISS": "red"}.get(row.status, "blue")
            console.print(f"  [{color}]{row.status}[/{color}] {row.item}: {row.detail}" + (f" → {row.recommendation}" if row.recommendation else ""))

    pending = [row for row in build_patch_queue(loaded_manifest) if row.status != "OK"]
    if pending:
        console.print(f"\n{len(pending)} parche(s) de RetroAchievements pendientes de resolver.")


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
    from .verify import VERIFY_METRIC_LABELS, report_verify, verify_collection

    parsed_platform = _platform(platform)
    catalog = _catalog(dat)
    cache_path = project_state_dir() / "scan-cache.sqlite3"
    scan_result = scan_directory(input, parsed_platform, dat_index=DatIndex(catalog), dat_path=dat, hash_cache=cache_path, workers=workers)
    report = verify_collection(scan_result, catalog)

    if format != "table":
        report_path = output or project_state_dir() / "reports" / f"verify.{format}"
        report_verify(report, report_path, format)
        console.print(f"[green]Informe de verificación guardado en {report_path}[/green]")
        if not report.clean:
            raise typer.Exit(code=1)
        return

    summary = Table(title="Verificación de colección")
    summary.add_column("Métrica")
    summary.add_column("Valor", justify="right")
    # Derivado de la lista compartida: cuando se añadió "Sets mixtos", esta
    # tabla se quedó atrás por estar escrita a mano.
    for key, label in VERIFY_METRIC_LABELS:
        summary.add_row(label, str(getattr(report, key)))
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
        console.print(f"[green]Importado[/green] {dat.name} ({dat.format}, {dat.header_mode}, juegos={dat.games}, roms={dat.roms}, recomendado={'sí' if dat.recommended else 'no'})")


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
        table = Table(title="Fuentes DAT en línea")
        for column in ["ID", "Etiqueta", "Formato", "Descarga directa", "URL"]:
            table.add_column(column)
        for item in list_dat_sources(parsed_platform.value):
            table.add_row(item.id, item.label, item.format, "sí" if item.direct_download else "no", item.url)
        console.print(table)
        return
    imported = download_and_import_source(source) if source else download_and_import_url(url or "", filename=filename)
    for dat in imported:
        console.print(f"[green]Descargado[/green] {dat.name} ({dat.format}, {dat.header_mode}, juegos={dat.games}, roms={dat.roms}, recomendado={'sí' if dat.recommended else 'no'})")


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
    kind: Annotated[str, typer.Option("--kind", help="archive_org, http_index, local_dir, zip_index o torrent.")],
    location: Annotated[str, typer.Option("--location", help="Ítem de archive.org, URL del índice, ruta de la carpeta, ruta/URL del ZIP o ruta del .torrent.")],
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
    profile: Annotated[str, typer.Option("--profile", help="Nombre de un perfil (`default`, uno recomendado o uno guardado) o ruta de un .yaml/.json.")] = "default",
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

    catalog = _catalog(dat)
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
        _profile(profile),
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

    try:
        report = run_download_plan(plan, dest, dat_index=DatIndex(catalog))
    except RuntimeError as exc:
        # Falta de espacio comprobada antes de empezar: aviso, no fallo del programa.
        console.print(f"[red]No se descargó nada:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    for outcome in report.outcomes:
        color = {"ok": "green", "present": "blue", "mismatch": "red", "error": "red", "cancelled": "yellow"}.get(outcome.status, "white")
        console.print(f"[{color}]{outcome.status_label}[/{color}] {outcome.file_name} {outcome.detail}")
    console.print(f"Descargados {report.downloaded}, con problemas {report.failed}, total {human_size(report.total_bytes)}.")
    if report.failed:
        raise typer.Exit(code=1)


@app.command("torrent-queue")
def torrent_queue(
    torrent: Annotated[Path, typer.Option("--torrent", exists=True, file_okay=True, dir_okay=False, readable=True)],
    dat: Annotated[Path, typer.Option("--dat", exists=True, file_okay=True, dir_okay=False, readable=True)],
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    scan: Annotated[Path | None, typer.Option("--scan", exists=True, file_okay=True, dir_okay=False, readable=True)] = None,
    profile: Annotated[str, typer.Option("--profile", help="Nombre de un perfil (`default`, uno recomendado o uno guardado) o ruta de un .yaml/.json.")] = "default",
    url: Annotated[str, typer.Option("--qbittorrent", help="URL de la Web UI de qBittorrent.")] = QBT_DEFAULT_URL,
    save_path: Annotated[str | None, typer.Option("--save-path", help="Carpeta de descarga que usará el cliente.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run/--queue", help="Solo muestra qué archivos se seleccionarían.")] = True,
) -> None:
    """Añade un .torrent a qBittorrent con solo los juegos que te faltan seleccionados."""
    plan, info = _torrent_plan(torrent, dat, platform, scan, profile)
    console.print(f"Torrent: [bold]{info.name}[/bold] · {len(info.files)} archivos · {human_size(info.total_size)}")
    console.print(f"Te faltan {len(plan.candidates)} ({human_size(plan.total_bytes)}); el resto se deseleccionará.")
    for candidate in plan.candidates[:20]:
        console.print(f"  · {candidate.title} → {candidate.inner_path}")
    if len(plan.candidates) > 20:
        console.print(f"  … y {len(plan.candidates) - 20} más")
    if dry_run:
        console.print("[yellow]Simulación:[/yellow] repite con --queue para añadirlo a qBittorrent.")
        console.print("Con otro cliente: añádelo a mano, selecciona esos archivos y luego usa `torrent-collect`.")
        return
    try:
        result = queue_plan(plan, torrent, client=QBittorrentClient(url), save_path=save_path)
    except TorrentClientError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Añadido a qBittorrent:[/green] {result['seleccionados']} archivos activos, {result['descartados']} descartados.")
    console.print("Cuando termine, recoge lo descargado con `torrent-collect`.")


@app.command("torrent-collect")
def torrent_collect(
    torrent: Annotated[Path, typer.Option("--torrent", exists=True, file_okay=True, dir_okay=False, readable=True)],
    dat: Annotated[Path, typer.Option("--dat", exists=True, file_okay=True, dir_okay=False, readable=True)],
    downloads: Annotated[Path, typer.Option("--downloads", exists=True, file_okay=False, dir_okay=True, readable=True, help="Carpeta donde descarga tu cliente.")],
    dest: Annotated[Path, typer.Option("--dest", help="Carpeta del romset donde instalar lo verificado.")],
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    scan: Annotated[Path | None, typer.Option("--scan", exists=True, file_okay=True, dir_okay=False, readable=True)] = None,
    profile: Annotated[str, typer.Option("--profile", help="Nombre de un perfil (`default`, uno recomendado o uno guardado) o ruta de un .yaml/.json.")] = "default",
) -> None:
    """Verifica lo que tu cliente ya descargó y lo copia al romset. Funciona con cualquier cliente."""
    plan, _info = _torrent_plan(torrent, dat, platform, scan, profile)
    report = collect_downloads(plan, downloads, dest, dat_index=DatIndex(_catalog(dat)))
    counts: dict[str, int] = {}
    for outcome in report.outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
        if outcome.status in {"mismatch", "incomplete"}:
            console.print(f"[yellow]{outcome.status_label}[/yellow] {outcome.file_name} {outcome.detail}")
    pending = " · ".join(f"{status}: {count}" for status, count in sorted(counts.items()) if status != "ok")
    console.print(f"[green]Instalados {report.downloaded}[/green] ({human_size(report.total_bytes)})" + (f" · {pending}" if pending else ""))
    console.print("Se copia, no se mueve: tu cliente sigue sembrando desde su carpeta.")


def _torrent_plan(torrent: Path, dat: Path, platform: str, scan: Path | None, profile: str):
    """Plan acotado a los archivos de un .torrent concreto."""
    parsed_platform = _platform(platform)
    info = read_torrent(torrent)
    source = RomSource(id=f"torrent-{torrent.stem}", label=torrent.name, kind="torrent", location=str(torrent), platform=parsed_platform.value)
    remote_files, errors = resolve_remote_files([source], refresh=True)
    for message in errors:
        console.print(f"[red]{message}[/red]")
    plan = build_download_plan(
        _catalog(dat),
        load_scan(scan) if scan else None,
        _profile(profile),
        remote_files,
        platform=parsed_platform,
    )
    return plan, info


@app.command()
def fixdat(
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    input: Annotated[Path, typer.Option("--input", exists=True, file_okay=True, dir_okay=True, readable=True)] = Path("."),
    dat: Annotated[Path, typer.Option("--dat", exists=True, file_okay=True, dir_okay=False, readable=True)] = ...,  # type: ignore[assignment]
    scan: Annotated[Path | None, typer.Option("--scan", exists=True, file_okay=True, dir_okay=False, readable=True, help="Reutiliza un escaneo guardado en vez de volver a escanear.")] = None,
    output: Annotated[Path | None, typer.Option("--output", help="Por defecto .retroperfect/reports/fixdat-<plataforma>.dat")] = None,
    workers: Annotated[int | None, typer.Option("--workers", min=1)] = None,
) -> None:
    """Exporta un DAT con solo lo que te falta, para dárselo a otra herramienta."""
    from .fixdat import build_fixdat, missing_roms

    parsed_platform = _platform(platform)
    catalog = _catalog(dat)
    scan_result = load_scan(scan) if scan else scan_directory(input, parsed_platform, dat_index=DatIndex(catalog), dat_path=dat, hash_cache=project_state_dir() / "scan-cache.sqlite3", workers=workers)
    faltan = missing_roms(catalog, scan_result)
    destino = output or project_state_dir() / "reports" / f"fixdat-{parsed_platform.value}.dat"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(build_fixdat(catalog, scan_result, parsed_platform), encoding="utf-8")
    roms = sum(len(items) for _game, items in faltan)
    console.print(f"[green]Fixdat guardado en {destino}[/green]: {len(faltan)} juegos, {roms} ROMs que te faltan.")
    if not faltan:
        console.print("La colección está completa según este DAT: el fixdat sale vacío.")


@app.command()
def export(
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    input: Annotated[Path, typer.Option("--input", exists=True, file_okay=True, dir_okay=True, readable=True)] = Path("."),
    dat: Annotated[Path | None, typer.Option("--dat", exists=True, file_okay=True, dir_okay=False, readable=True)] = None,
    scan: Annotated[Path | None, typer.Option("--scan", exists=True, file_okay=True, dir_okay=False, readable=True)] = None,
    manifest: Annotated[Path | None, typer.Option("--manifest", exists=True, file_okay=True, dir_okay=False, readable=True, help="Usa las rutas de destino del plan en vez de las actuales.")] = None,
    format: Annotated[str, typer.Option("--format", help="lpl (RetroArch), gamelist (EmulationStation/Batocera) o pegasus (Pegasus Frontend).")] = "lpl",
    thumbnails: Annotated[Path | None, typer.Option("--thumbnails", exists=True, file_okay=False, dir_okay=True, help="Carpeta de carátulas (la de `retroperfect thumbnails`): se enlazan en el gamelist.")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    workers: Annotated[int | None, typer.Option("--workers", min=1)] = None,
) -> None:
    """Exporta la colección al formato que consume tu frontend."""
    from .frontends import libretro_system, write_gamelist, write_pegasus, write_retroarch_playlist

    if format not in {"lpl", "gamelist", "pegasus"}:
        raise typer.BadParameter("Formatos: lpl, gamelist o pegasus.", param_hint="--format")
    parsed_platform = _platform(platform)
    catalog = _catalog(dat) if dat else None
    scan_result = load_scan(scan) if scan else scan_directory(input, parsed_platform, dat_index=DatIndex(catalog) if catalog else None, dat_path=dat, hash_cache=project_state_dir() / "scan-cache.sqlite3", workers=workers)
    loaded = load_manifest(manifest) if manifest else None

    if format == "lpl":
        destino = output or Path(f"{libretro_system(parsed_platform)}.lpl")
        write_retroarch_playlist(scan_result, destino, loaded)
    elif format == "pegasus":
        destino = output or Path("metadata.pegasus.txt")
        write_pegasus(scan_result, destino, loaded, thumbnails_dir=thumbnails)
    else:
        destino = output or Path("gamelist.xml")
        write_gamelist(scan_result, destino, loaded, thumbnails_dir=thumbnails)
    console.print(f"[green]Exportado a {destino}[/green] ({len(scan_result.roms)} ROMs del escaneo).")
    if loaded is None:
        console.print("Sin --manifest se listan las rutas actuales; pásalo para listar las de la colección curada.")


@app.command()
def thumbnails(
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    input: Annotated[Path, typer.Option("--input", exists=True, file_okay=True, dir_okay=True, readable=True)] = Path("."),
    dat: Annotated[Path, typer.Option("--dat", exists=True, file_okay=True, dir_okay=False, readable=True)] = ...,  # type: ignore[assignment]
    scan: Annotated[Path | None, typer.Option("--scan", exists=True, file_okay=True, dir_okay=False, readable=True)] = None,
    manifest: Annotated[Path | None, typer.Option("--manifest", exists=True, file_okay=True, dir_okay=False, readable=True, help="Descarga solo las carátulas de lo que el plan conserva.")] = None,
    dest: Annotated[Path, typer.Option("--dest", help="Carpeta de carátulas.")] = Path("thumbnails"),
    retroarch: Annotated[bool, typer.Option("--retroarch", help="Guarda dentro de la subcarpeta del sistema, que es donde RetroArch las busca.")] = False,
    kinds: Annotated[str, typer.Option("--kinds", help="boxart, snap y/o title, separados por comas.")] = "boxart",
    limit: Annotated[int | None, typer.Option("--limit")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite/--skip-existing")] = False,
    workers: Annotated[int | None, typer.Option("--workers", min=1)] = None,
) -> None:
    """Descarga las carátulas de Libretro emparejadas por el nombre del DAT."""
    from .frontends import libretro_system
    from .thumbnails import KINDS, download_thumbnails, has_thumbnails

    parsed_platform = _platform(platform)
    elegidos = tuple(item.strip() for item in kinds.split(",") if item.strip())
    if desconocidos := [item for item in elegidos if item not in KINDS]:
        raise typer.BadParameter(f"Tipos desconocidos: {', '.join(desconocidos)}. Usa: {', '.join(KINDS)}.", param_hint="--kinds")
    if not has_thumbnails(parsed_platform):
        console.print(f"[yellow]Libretro no publica carátulas de {platform_spec(parsed_platform).short_name}.[/yellow]")
        raise typer.Exit(code=1)

    catalog = _catalog(dat)
    scan_result = load_scan(scan) if scan else scan_directory(input, parsed_platform, dat_index=DatIndex(catalog), dat_path=dat, hash_cache=project_state_dir() / "scan-cache.sqlite3", workers=workers)
    # RetroArch busca en <thumbnails>/<Nombre del sistema>/Named_Boxarts/, así
    # que sin la subcarpeta hay que moverlas a mano para que las vea.
    carpeta = dest / libretro_system(parsed_platform) if retroarch else dest
    resultados = download_thumbnails(scan_result, carpeta, manifest=load_manifest(manifest) if manifest else None, kinds=elegidos, limit=limit, overwrite=overwrite)

    conteo: dict[str, int] = {}
    for resultado in resultados:
        conteo[resultado.status] = conteo.get(resultado.status, 0) + 1
    for resultado in resultados:
        if resultado.status == "error":
            console.print(f"[red]error[/red] {resultado.title}: {resultado.detail}")
    resumen = " · ".join(f"{estado}: {total}" for estado, total in sorted(conteo.items()))
    console.print(f"[green]Carátulas en {carpeta}[/green] — {resumen}")
    console.print("Las que Libretro no tiene salen como 'ausente': no se descarga ninguna aproximada.")


@app.command("dat-list")
def dat_list() -> None:
    """Lista los DATs instalados."""
    table = Table(title="DATs instalados")
    for column in ["Nombre", "Fuente", "Formato", "Cabecera", "Recomendado", "Juegos", "ROMs", "P/C", "Ruta"]:
        table.add_column(column)
    for dat in list_installed_dats():
        table.add_row(dat.name, dat.source, dat.format, dat.header_mode, "sí" if dat.recommended else "no", str(dat.games), str(dat.roms), "sí" if dat.parent_clone else "no", dat.path)
    console.print(table)


@app.command("dat-compare")
def dat_compare(
    left: Annotated[Path, typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True)],
    right: Annotated[Path, typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True)],
) -> None:
    """Compara dos DATs por grupos de juegos y hashes de ROMs."""
    comparison = compare_dats(left, right)
    table = Table(title=f"{comparison.left_name} vs {comparison.right_name}")
    table.add_column("Métrica")
    table.add_column("Valor")
    table.add_row("Juegos en común", str(comparison.common_games))
    table.add_row("Juegos solo en el primero", str(comparison.left_only_games))
    table.add_row("Juegos solo en el segundo", str(comparison.right_only_games))
    table.add_row("ROMs en común", str(comparison.common_roms))
    table.add_row("ROMs solo en el primero", str(comparison.left_only_roms))
    table.add_row("ROMs solo en el segundo", str(comparison.right_only_roms))
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
        console.print("[green]La configuración está lista.[/green]")
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

    try:
        lines = list(restore_session(session))
    except RuntimeError as exc:
        console.print(f"[red]No se pudo restaurar:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    for line in lines:
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
def rename(
    platform: Annotated[str, typer.Option("--platform")] = "nes",
    input: Annotated[Path, typer.Option("--input", exists=True, file_okay=True, dir_okay=True, readable=True)] = Path("."),
    dat: Annotated[Path, typer.Option("--dat", exists=True, file_okay=True, dir_okay=False, readable=True)] = ...,  # type: ignore[assignment]
    scan: Annotated[Path | None, typer.Option("--scan", exists=True, file_okay=True, dir_okay=False, readable=True, help="Reutiliza un escaneo guardado en vez de volver a escanear.")] = None,
    confirm: Annotated[bool, typer.Option("--confirm/--no-confirm", help="Sin --confirm solo se muestra qué se renombraría.")] = False,
    limit: Annotated[int, typer.Option("--limit", help="Máximo de filas a listar.")] = 50,
    workers: Annotated[int | None, typer.Option("--workers", min=1)] = None,
) -> None:
    """Renombra en el sitio los archivos que no se llaman como dice el DAT."""
    from .renaming import apply_renames, plan_renames

    parsed_platform = _platform(platform)
    catalog = _catalog(dat)
    scan_result = load_scan(scan) if scan else scan_directory(input, parsed_platform, dat_index=DatIndex(catalog), dat_path=dat, hash_cache=project_state_dir() / "scan-cache.sqlite3", workers=workers)
    plans = plan_renames(scan_result)
    renombrables = [plan for plan in plans if plan.can_apply]
    omitidos = [plan for plan in plans if not plan.can_apply]

    if not plans:
        console.print("[green]Todos los archivos reconocidos se llaman como dice el DAT.[/green]")
        return

    table = Table(title=f"Renombrados · {platform_spec(parsed_platform).short_name}")
    for column in ["Actual", "Pasaría a llamarse", "Nota"]:
        table.add_column(column)
    for plan in plans[:limit]:
        table.add_row(plan.current_name, plan.expected_name if plan.can_apply else "—", plan.skipped_reason)
    console.print(table)
    if len(plans) > limit:
        console.print(f"… y {len(plans) - limit} más.")
    console.print(f"Se renombrarían {len(renombrables)}; omitidos {len(omitidos)}.")

    if not renombrables:
        return
    if not confirm:
        console.print("[yellow]Simulación:[/yellow] repite con --confirm para renombrar de verdad.")
        return
    for line in apply_renames(plans):
        console.print(line)
    console.print("Vuelve a escanear para que la colección refleje los nombres nuevos.")


@app.command("scan-diff")
def scan_diff(
    before: Annotated[Path, typer.Option("--before", exists=True, file_okay=True, dir_okay=False, readable=True, help="Escaneo antiguo (.retroperfect/scans/<id>.json).")],
    after: Annotated[Path, typer.Option("--after", exists=True, file_okay=True, dir_okay=False, readable=True, help="Escaneo nuevo; por defecto el último.")] = Path(".retroperfect/scans/latest.json"),
    limit: Annotated[int, typer.Option("--limit", help="Máximo de filas a listar.")] = 50,
    format: Annotated[str, typer.Option("--format", help="table o json.")] = "table",
) -> None:
    """Compara dos escaneos: altas, bajas, movidos y archivos que cambiaron de contenido."""
    from .scan_diff import KIND_LABELS, diff_scans

    if format not in {"table", "json"}:
        raise typer.BadParameter("Formatos: table o json.", param_hint="--format")
    diff = diff_scans(load_scan(before), load_scan(after))
    if format == "json":
        console.print_json(diff.model_dump_json())
        return

    table = Table(title="Resumen de cambios")
    table.add_column("Métrica")
    table.add_column("Valor", justify="right")
    for etiqueta, valor in [
        ("Sin cambios", diff.unchanged),
        ("Añadidos", len(diff.added)),
        ("Eliminados", len(diff.removed)),
        ("Cambiaron de contenido", len(diff.changed)),
        ("Movidos o renombrados", len(diff.moved)),
        ("Coincidían con el DAT (antes)", diff.matched_before),
        ("Coinciden con el DAT (ahora)", diff.matched_after),
    ]:
        table.add_row(etiqueta, str(valor))
    console.print(table)

    if diff.identical:
        console.print("[green]Los dos escaneos describen la misma colección.[/green]")
        return

    detalle = Table(title=f"Diferencias ({min(len(diff.entries), limit)} de {len(diff.entries)})")
    for column in ["Qué pasó", "Archivo", "Detalle"]:
        detalle.add_column(column)
    for entry in diff.entries[:limit]:
        color = {"cambiado": "red", "eliminado": "yellow", "añadido": "green"}.get(entry.kind, "blue")
        detalle.add_row(f"[{color}]{KIND_LABELS.get(entry.kind, entry.kind)}[/{color}]", entry.name, entry.detail)
    console.print(detalle)
    if diff.changed:
        console.print(
            f"[red]{len(diff.changed)} archivo(s) cambiaron de contenido sin cambiar de nombre.[/red] "
            "Es lo que no se nota mirando la carpeta: revisa si fue a propósito antes de curar."
        )


@app.command("cache-export")
def cache_export(
    output: Annotated[Path, typer.Option("--output", help="Archivo JSON donde guardar la caché.")] = Path("retroperfect-cache.json"),
) -> None:
    """Guarda la caché de hashes en un archivo, para respaldarla o moverla."""
    import json as json_module

    from .scan_cache import ScanHashCache

    cache = ScanHashCache(project_state_dir() / "scan-cache.sqlite3")
    try:
        filas = cache.export_rows()
    finally:
        cache.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json_module.dumps({"entries": filas}, indent=2), encoding="utf-8")
    console.print(f"[green]Exportadas {len(filas)} entradas a {output}[/green]")
    if filas:
        console.print("La caché se valida por ruta, tamaño y fecha de modificación: sirve de respaldo y para una colección que cambie de sitio, no para otra máquina con otras rutas.")


@app.command("cache-import")
def cache_import(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True, help="Archivo generado con cache-export.")],
    rebase: Annotated[str | None, typer.Option("--rebase", help="Reescribe el principio de las rutas: VIEJO=NUEVO. Para cuando la colección cambió de unidad o de punto de montaje.")] = None,
) -> None:
    """Carga una caché de hashes exportada, opcionalmente reapuntando las rutas."""
    import json as json_module

    from .scan_cache import ScanHashCache

    try:
        payload = json_module.loads(path.read_text(encoding="utf-8"))
        filas = list(payload["entries"])
    except (ValueError, KeyError, TypeError) as exc:
        raise typer.BadParameter(f"{path.name} no parece una caché exportada: {exc}") from exc

    pareja: tuple[str, str] | None = None
    if rebase:
        if "=" not in rebase:
            raise typer.BadParameter("Formato: --rebase /ruta/vieja=/ruta/nueva", param_hint="--rebase")
        viejo, nuevo = rebase.split("=", 1)
        pareja = (viejo, nuevo)

    cache = ScanHashCache(project_state_dir() / "scan-cache.sqlite3")
    try:
        entradas = cache.import_rows(filas, rebase=pareja)
        utiles = cache.usable_rows()
    finally:
        cache.close()
    # `utiles` mira la caché entera, no solo lo que acaba de entrar: importar es
    # acumulativo y lo que el usuario quiere saber es cuánto le sirve ya.
    console.print(f"[green]Importadas {entradas} entradas.[/green]")
    console.print(f"La caché puede reutilizar {utiles} entrada(s) de este equipo: ese trabajo se lo ahorra el próximo escaneo.")
    if entradas and not utiles:
        console.print("[yellow]Ninguna entrada coincide con un archivo de este equipo.[/yellow] Si la colección está en otra ruta, prueba con --rebase.")


@app.command("cache-clear")
def cache_clear(
    confirm: Annotated[bool, typer.Option("--confirm/--no-confirm")] = False,
) -> None:
    """Vacía la caché de hashes. El siguiente escaneo volverá a calcularlo todo."""
    from .scan_cache import ScanHashCache

    cache = ScanHashCache(project_state_dir() / "scan-cache.sqlite3")
    try:
        if not confirm:
            console.print(f"[yellow]La caché tiene {cache.count()} entradas. Vaciarla obliga a rehashear la colección entera; repite con --confirm.[/yellow]")
            raise typer.Exit(code=1)
        habia = cache.clear()
    finally:
        cache.close()
    console.print(f"[green]Caché vaciada: {habia} entradas eliminadas.[/green]")


@app.command()
def undo(
    journal: Annotated[Path | None, typer.Option("--journal", exists=True, file_okay=True, dir_okay=False, readable=True, help="Journal a deshacer; por defecto el último de .retroperfect/applied/.")] = None,
    confirm: Annotated[bool, typer.Option("--confirm/--no-confirm", help="Sin --confirm solo se muestra qué se deshará.")] = False,
    limit: Annotated[int, typer.Option("--limit")] = 50,
) -> None:
    """Deshace una aplicación: devuelve la colección a como estaba antes."""
    from .undoing import apply_undo, latest_journal, plan_undo

    ruta = journal or latest_journal()
    if ruta is None:
        console.print("No hay ninguna aplicación registrada en .retroperfect/applied/.")
        raise typer.Exit(code=1)
    try:
        plan = plan_undo(ruta)
    except ValueError as exc:
        console.print(f"[red]No se puede deshacer:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not plan.steps:
        console.print(f"{ruta.name} no registra ninguna operación que se pueda deshacer.")
        if plan.hard_deleted:
            console.print(f"[yellow]{plan.hard_deleted} archivo(s) se borraron definitivamente y no se pueden recuperar.[/yellow]")
        return

    console.print(f"Journal: [bold]{ruta.name}[/bold] · aplicado el {plan.applied_at or 'desconocido'} · plataforma {plan.platform or 'desconocida'}")
    table = Table(title=f"Qué se deshará ({min(len(plan.steps), limit)} de {len(plan.steps)})")
    for column in ["Acción", "Archivo", "Detalle"]:
        table.add_column(column)
    for step in plan.steps[:limit]:
        color = "green" if step.can_apply else "yellow"
        table.add_row(f"[{color}]{step.action if step.can_apply else 'omitido'}[/{color}]", Path(step.path).name, step.detail if step.can_apply else step.skipped_reason)
    console.print(table)
    console.print(f"Se deshacen {len(plan.applicable)} de {len(plan.steps)} operaciones.")
    if plan.hard_deleted:
        console.print(f"[yellow]{plan.hard_deleted} archivo(s) se borraron definitivamente y no se pueden recuperar.[/yellow]")

    if not plan.applicable:
        return
    if not confirm:
        console.print("[yellow]Simulación:[/yellow] repite con --confirm para deshacer de verdad.")
        return
    for line in apply_undo(plan):
        console.print(line)


@app.command("sync-device")
def sync_device(
    scan: Annotated[Path, typer.Option("--scan", exists=True, file_okay=True, dir_okay=False, readable=True, help="Escaneo de la colección.")],
    dest: Annotated[Path, typer.Option("--dest", help="Carpeta del dispositivo (la SD, la consola, el disco).")],
    budget: Annotated[str, typer.Option("--budget", help="Cuánto cabe: 32GB, 512MiB o el número de bytes.")],
    profile: Annotated[str, typer.Option("--profile", help="Nombre de un perfil (`default`, uno recomendado o uno guardado) o ruta de un .yaml/.json.")] = "default",
    outputs: Annotated[str, typer.Option("--outputs")] = "main",
    order: Annotated[str, typer.Option("--order", help="En qué orden entran los juegos: size (más pequeños primero), name o ra.")] = "size",
    containers: Annotated[ContainerMode, typer.Option("--containers")] = ContainerMode.KEEP,
    limit: Annotated[int, typer.Option("--limit", help="Máximo de filas a listar.")] = 30,
    confirm: Annotated[bool, typer.Option("--confirm/--no-confirm", help="Sin --confirm solo se muestra qué entraría.")] = False,
    link: Annotated[bool, typer.Option("--link", help="Enlaza en vez de copiar si el dispositivo está en el mismo disco.")] = False,
) -> None:
    """Llena un dispositivo con lo que quepa de la colección, sin pasarse del tamaño."""
    from .device_sync import SYNC_ORDERS, parse_budget, plan_device_sync
    from .download_plan import human_size

    if order not in SYNC_ORDERS:
        raise typer.BadParameter(f"Órdenes: {', '.join(SYNC_ORDERS)}.", param_hint="--order")
    try:
        presupuesto = parse_budget(budget)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--budget") from exc

    scan_result = load_scan(scan)
    selection_profile = _profile(profile)
    selected_outputs = [OutputBucket(item.strip()) for item in outputs.split(",") if item.strip()]
    completo = build_manifest(scan_result, selection_profile, selected_outputs, output_dir=dest, action=ActionMode.COPY, container_mode=containers)
    manifest, report = plan_device_sync(completo, scan_result, dest, presupuesto, order)

    console.print(f"Dispositivo: [bold]{dest}[/bold] · caben {human_size(presupuesto)} · orden: {SYNC_ORDERS[order]}")
    table = Table(title=f"Entran {len(report.included)} juego(s) de {len(report.included) + len(report.excluded)}")
    for column in ["Juego", "Tamaño", "Archivos", "RA"]:
        table.add_column(column)
    for juego in report.included[:limit]:
        table.add_row(juego.title, human_size(juego.size), str(juego.files), "🏆" if juego.ra else "")
    console.print(table)
    if len(report.included) > limit:
        console.print(f"… y {len(report.included) - limit} más.")
    console.print(
        f"Ocuparán {human_size(report.bytes_planned)} y quedarán {human_size(report.bytes_left)} libres. "
        f"Con logros: {report.ra_included}. Se quedan fuera {len(report.excluded)} juego(s)."
    )
    if report.excluded:
        mayores = sorted(report.excluded, key=lambda juego: juego.size, reverse=True)[:3]
        console.print("Los más grandes que no caben: " + ", ".join(f"{juego.title} ({human_size(juego.size)})" for juego in mayores))

    if not manifest.entries:
        console.print("[yellow]No cabe ni un juego con ese presupuesto.[/yellow]")
        raise typer.Exit(code=1)
    path = save_manifest(manifest, project_state_dir() / "manifests" / "latest-device.json")
    console.print(f"Plan guardado en {path}")
    if not confirm:
        console.print("[yellow]Simulación:[/yellow] repite con --confirm para copiar al dispositivo.")
        return
    try:
        completed = apply_manifest(manifest, confirm=True, link=link)
    except (RuntimeError, OSError) as exc:
        console.print(f"[red]No se sincronizó:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]{len(completed)} operación(es) en {dest}.[/green] Lo que ya estaba y no había cambiado se omitió.")


@app.command()
def curate(
    root: Annotated[Path, typer.Option("--root", exists=True, file_okay=False, dir_okay=True, readable=True, help="Carpeta del romset, con una subcarpeta por sistema.")],
    output_dir: Annotated[Path | None, typer.Option("--output-dir", help="Dónde dejar la colección curada; cada sistema en su subcarpeta.")] = None,
    profile: Annotated[str, typer.Option("--profile", help="Nombre de un perfil (`default`, uno recomendado o uno guardado) o ruta de un .yaml/.json.")] = "default",
    outputs: Annotated[str, typer.Option("--outputs")] = "main",
    platforms: Annotated[str | None, typer.Option("--platforms", help="Limita a estas plataformas, separadas por comas.")] = None,
    containers: Annotated[ContainerMode, typer.Option("--containers")] = ContainerMode.KEEP,
    action: Annotated[ActionMode, typer.Option("--action")] = ActionMode.COPY,
    confirm: Annotated[bool, typer.Option("--confirm/--no-confirm", help="Sin --confirm se planifica y no se toca nada.")] = False,
    workers: Annotated[int | None, typer.Option("--workers", min=1)] = None,
) -> None:
    """Cura un romset de varios sistemas de una pasada, una subcarpeta por plataforma."""
    from .batch import BatchOutcome, BatchReport, discover_targets

    pedidas = {_platform(item.strip()) for item in platforms.split(",") if item.strip()} if platforms else None
    objetivos = discover_targets(root, pedidas)
    if not objetivos:
        console.print(f"No hay subcarpetas en {root}. Un romset multi-sistema tiene una carpeta por plataforma.")
        raise typer.Exit(code=1)

    selection_profile = _profile(profile)
    selected_outputs = [OutputBucket(item.strip()) for item in outputs.split(",") if item.strip()]
    report = BatchReport(root=str(root))
    cache_path = project_state_dir() / "scan-cache.sqlite3"

    for objetivo in objetivos:
        if not objetivo.can_curate:
            report.skipped.append(objetivo)
            continue
        outcome = BatchOutcome(target=objetivo)
        try:
            catalog = _catalog(Path(objetivo.dat))
            scan_result = scan_directory(Path(objetivo.folder), Platform(objetivo.platform), dat_index=DatIndex(catalog), dat_path=Path(objetivo.dat), hash_cache=cache_path, workers=workers)
            save_scan(scan_result)
            outcome.roms = len(scan_result.roms)
            outcome.matched = sum(1 for rom in scan_result.roms if rom.dat_game is not None)
            destino = (output_dir / objetivo.platform) if output_dir else None
            manifest = build_manifest(scan_result, selection_profile, selected_outputs, output_dir=destino, action=action, container_mode=containers)
            outcome.kept = len(manifest.entries)
            outcome.manifest = str(save_manifest(manifest, project_state_dir() / "manifests" / f"batch-{objetivo.platform}.json"))
            if confirm:
                if destino is None:
                    raise typer.BadParameter("--output-dir es obligatorio para aplicar de verdad.")
                outcome.applied = len(apply_manifest(manifest, confirm=True))
        except typer.BadParameter:
            raise
        except Exception as exc:  # noqa: BLE001 - una plataforma que falla no corta el resto del romset
            outcome.error = str(exc)
        report.outcomes.append(outcome)

    table = Table(title=f"Romset de {root}")
    for column in ["Carpeta", "Plataforma", "DAT", "ROMs", "En DAT", "Se conservan", "Aplicadas"]:
        table.add_column(column)
    for outcome in report.outcomes:
        color = "red" if not outcome.ok else "white"
        table.add_row(
            f"[{color}]{outcome.target.name}[/{color}]",
            outcome.target.platform_label,
            outcome.target.dat_name,
            str(outcome.roms),
            str(outcome.matched),
            str(outcome.kept),
            str(outcome.applied) if confirm else "—",
        )
    console.print(table)

    for outcome in report.outcomes:
        if not outcome.ok:
            console.print(f"[red]{outcome.target.name}:[/red] {outcome.error}")
    if report.skipped:
        console.print("\n[bold]Carpetas no curadas[/bold]")
        for objetivo in report.skipped:
            console.print(f"  [yellow]{objetivo.name}[/yellow]: {objetivo.skipped_reason}")

    console.print(f"\nCuradas {report.curated} plataforma(s), {report.total_kept} operación(es) planificadas, {len(report.skipped)} carpeta(s) sin curar.")
    if not confirm and report.curated:
        console.print("[yellow]Simulación:[/yellow] repite con --confirm --output-dir <carpeta> para aplicar.")
    if report.failed:
        raise typer.Exit(code=1)


@app.command()
def doctor() -> None:
    """Estado de la instalación: versión, carpetas, formatos soportados y configuración."""
    from .doctor import build_doctor_rows

    table = Table(title="Estado de la instalación")
    table.add_column("")
    table.add_column("Qué")
    table.add_column("Estado")
    table.add_column("Nota")
    for row in build_doctor_rows():
        color = {"OK": "green", "WARN": "yellow", "MISS": "red"}.get(row.status, "blue")
        table.add_row(f"[{color}]{row.status}[/{color}]", row.item, row.detail, row.recommendation)
    console.print(table)
    console.print("Pega esta tabla si abres un issue: es lo primero que hace falta para reproducir un fallo.")


@app.command()
def gui(
    host: str = "127.0.0.1",
    port: int = 8080,
    exit_on_idle: Annotated[bool, typer.Option("--exit-on-idle/--no-exit-on-idle", help="Cierra la aplicación cuando no queda ningún navegador conectado.")] = False,
    allow_remote: Annotated[bool, typer.Option("--allow-remote", help="Permite escuchar en una dirección accesible desde la red. La interfaz no pide credenciales: cualquiera que llegue al puerto podrá explorar tus carpetas y borrar archivos.")] = False,
    lang: Annotated[str | None, typer.Option("--lang", help="Idioma de la interfaz: es o en. Por defecto, el de la variable RETROPERFECT_LANG o el del sistema.")] = None,
) -> None:
    """Arranca la interfaz local NiceGUI."""
    from .gui import run
    from .i18n import set_language

    if lang:
        set_language(lang)

    try:
        run(host=host, port=port, exit_on_idle=exit_on_idle, allow_remote=allow_remote)
    except RuntimeError as exc:
        console.print(f"[red]No se arrancó la interfaz:[/red] {exc}")
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
