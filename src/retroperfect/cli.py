from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .dat import DatIndex, parse_dat
from .dat_manager import compare_dats, download_and_import_source, download_and_import_url, import_dat_file, list_installed_dats, validate_setup
from .dat_sources import list_dat_sources
from .manifest_io import apply_manifest, load_manifest, report_manifest, save_manifest
from .models import ActionMode, ExportLayout, OutputBucket, Platform
from .paths import project_state_dir
from .platforms import platform_options, platform_spec
from .profile import load_profile
from .ra import annotate_scan_with_ra, sync_ra_hashes, sync_ra_patch_details
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


@app.command()
def gui(host: str = "127.0.0.1", port: int = 8080) -> None:
    """Arranca la interfaz local NiceGUI."""
    from .gui import run

    run(host=host, port=port)


if __name__ == "__main__":
    app()
