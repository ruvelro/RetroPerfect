from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from .dat import parse_dat
from .dat_sources import DAT_SOURCES, dat_download_dir, download_dat, download_url
from .models import Platform
from .platforms import platform_from_dat_name, platform_spec


class DatMetadata(BaseModel):
    id: str
    path: str
    source: str
    imported_at: datetime
    format: str
    name: str
    description: str | None = None
    platform: str | None = None
    games: int
    roms: int
    parent_clone: bool
    header_mode: str = "unknown"
    recommended: bool = False
    regions: list[str]
    notes: str = ""


class DatComparison(BaseModel):
    left_name: str
    right_name: str
    left_only_games: int
    right_only_games: int
    common_games: int
    left_only_roms: int
    right_only_roms: int
    common_roms: int


def registry_path() -> Path:
    path = dat_download_dir() / "registry.json"
    if not path.exists():
        path.write_text("[]", encoding="utf-8")
    return path


def list_installed_dats() -> list[DatMetadata]:
    rows = json.loads(registry_path().read_text(encoding="utf-8"))
    dats = [DatMetadata.model_validate(row) for row in rows]
    return [dat for dat in dats if Path(dat.path).exists()]


def save_registry(dats: list[DatMetadata]) -> None:
    seen: dict[str, DatMetadata] = {dat.id: dat for dat in dats}
    registry_path().write_text(json.dumps([dat.model_dump(mode="json") for dat in seen.values()], indent=2), encoding="utf-8")


def register_dat(path: Path, source: str = "manual") -> DatMetadata:
    metadata = inspect_dat(path, source=source)
    dats = [dat for dat in list_installed_dats() if dat.path != metadata.path]
    dats.append(metadata)
    save_registry(dats)
    return metadata


def import_dat_file(path: Path, source: str = "manual") -> list[DatMetadata]:
    if path.suffix.lower() == ".zip":
        return import_dat_zip(path, source=source)
    destination = dat_download_dir() / "imported" / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve() != destination.resolve():
        shutil.copy2(path, destination)
    return [register_dat(destination, source=source)]


def import_dat_zip(path: Path, source: str = "manual-zip") -> list[DatMetadata]:
    destination_dir = dat_download_dir() / "imported" / path.stem
    destination_dir.mkdir(parents=True, exist_ok=True)
    imported: list[DatMetadata] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            suffix = Path(info.filename).suffix.lower()
            if info.is_dir() or suffix not in {".dat", ".xml"}:
                continue
            destination = destination_dir / Path(info.filename).name
            destination.write_bytes(archive.read(info))
            imported.append(register_dat(destination, source=source))
    if not imported:
        raise ValueError("ZIP does not contain .dat or .xml files.")
    return imported


def download_and_import_source(source_id: str) -> list[DatMetadata]:
    source = next((item for item in DAT_SOURCES if item.id == source_id), None)
    if source is None:
        raise ValueError(f"Unknown DAT source: {source_id}")
    if not source.direct_download:
        raise RuntimeError(f"{source.label} requires browser preparation. Open {source.url} and import the resulting ZIP.")
    path = download_dat(source_id)
    return import_dat_file(path, source=source.label)


def download_and_import_url(url: str, filename: str | None = None, source: str = "custom-url") -> list[DatMetadata]:
    path = download_url(url, filename=filename)
    return import_dat_file(path, source=source)


def inspect_dat(path: Path, source: str = "manual", platform: Platform | None = None) -> DatMetadata:
    if path.suffix.lower() == ".zip":
        return inspect_dat_zip(path, source=source)[0]
    catalog = parse_dat(path)
    fmt = detect_dat_format(path)
    detected_platform = platform or platform_from_dat_name(" ".join(item for item in [catalog.name or "", catalog.description or "", path.name] if item))
    groups = {game.group_key for game in catalog.games}
    regions = sorted({region for game in catalog.games for region in game.releases})
    rom_count = sum(len(game.roms) for game in catalog.games)
    parent_clone = any(game.cloneof for game in catalog.games)
    header_mode = detect_header_mode(path)
    recommended = _is_recommended_dat(header_mode, parent_clone, detected_platform)
    return DatMetadata(
        id=str(path.resolve()),
        path=str(path),
        source=source,
        imported_at=datetime.now(timezone.utc),
        format=fmt,
        name=catalog.name or path.stem,
        description=catalog.description,
        platform=detected_platform.value if detected_platform else None,
        games=len(groups),
        roms=rom_count,
        parent_clone=parent_clone,
        header_mode=header_mode,
        recommended=recommended,
        regions=regions,
        notes=_dat_notes(parent_clone, header_mode, recommended, detected_platform),
    )


def inspect_dat_zip(path: Path, source: str = "manual-zip") -> list[DatMetadata]:
    inspected: list[DatMetadata] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            suffix = Path(info.filename).suffix.lower()
            if info.is_dir() or suffix not in {".dat", ".xml"}:
                continue
            destination = dat_download_dir() / "tmp-inspect" / Path(info.filename).name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(info))
            inspected.append(inspect_dat(destination, source=source))
    if not inspected:
        raise ValueError("ZIP does not contain .dat or .xml files.")
    return inspected


def suggest_dat_for_source(source: Path | None, platform: Platform = Platform.NES) -> DatMetadata | None:
    installed = list_installed_dats()
    if not installed:
        return None
    installed = [dat for dat in installed if dat.platform in {None, platform.value}]
    if not installed:
        return None
    spec = platform_spec(platform)
    source_text = str(source or "").lower()
    prefer_headered = platform == Platform.NES and "unheadered" not in source_text
    if "headered" in source_text and "unheadered" not in source_text:
        prefer_headered = True
    if "unheadered" in source_text:
        prefer_headered = False

    def score(dat: DatMetadata) -> tuple[int, int, int]:
        mode_score = 0
        if platform == Platform.NES:
            if prefer_headered and dat.header_mode == "headered":
                mode_score = 2
            elif not prefer_headered and dat.header_mode in {"unheadered", "headered"}:
                mode_score = 2 if dat.header_mode == "unheadered" else 1
        elif spec.dat_aliases and any(alias.lower() in dat.name.lower() for alias in spec.dat_aliases):
            mode_score = 2
        recommended_score = 1 if dat.recommended else 0
        parent_clone_score = 1 if dat.parent_clone else 0
        return (mode_score, recommended_score, parent_clone_score)

    return sorted(installed, key=score, reverse=True)[0]


def detect_dat_format(path: Path) -> str:
    with path.open(encoding="utf-8", errors="replace") as fh:
        prefix = fh.read(256).lstrip()
    if prefix.startswith("<") or prefix.startswith("<?xml"):
        return "LogiqX XML"
    return "clrmamepro"


def detect_header_mode(path: Path) -> str:
    with path.open(encoding="utf-8", errors="replace") as fh:
        text = fh.read(20000).lower()
    name = path.name.lower()
    if "unheadered" in name or "unheadered" in text:
        return "unheadered"
    if "headered" in name or ' header="' in text or " header " in text:
        return "headered"
    return "unknown"


def _is_recommended_dat(header_mode: str, parent_clone: bool, platform: Platform | None) -> bool:
    if platform == Platform.NES:
        return header_mode == "headered"
    if platform:
        return parent_clone or header_mode != "unknown"
    return parent_clone


def _dat_notes(parent_clone: bool, header_mode: str, recommended: bool, platform: Platform | None) -> str:
    parts = []
    if platform:
        parts.append(f"Detectado: {platform_spec(platform).short_name}")
    if platform == Platform.NES:
        if recommended:
            parts.append("Recomendado NES: headered")
        elif header_mode == "unheadered":
            parts.append("Valido, pero para uso/emulacion NES se recomienda headered")
        else:
            parts.append("Modo header desconocido")
    else:
        parts.append("Variante DAT recomendable" if recommended else "Revisa que coincida con el formato del romset")
    parts.append("Parent/Clone ideal para 1G1R" if parent_clone else "Sin Parent/Clone: 1G1R por nombre")
    return " · ".join(parts)


def compare_dats(left: Path, right: Path) -> DatComparison:
    left_catalog = parse_dat(left)
    right_catalog = parse_dat(right)
    left_games = {game.group_key for game in left_catalog.games}
    right_games = {game.group_key for game in right_catalog.games}
    left_roms = {rom.sha1 or rom.md5 or rom.crc32 or rom.name for game in left_catalog.games for rom in game.roms}
    right_roms = {rom.sha1 or rom.md5 or rom.crc32 or rom.name for game in right_catalog.games for rom in game.roms}
    return DatComparison(
        left_name=left_catalog.name or left.stem,
        right_name=right_catalog.name or right.stem,
        left_only_games=len(left_games - right_games),
        right_only_games=len(right_games - left_games),
        common_games=len(left_games & right_games),
        left_only_roms=len(left_roms - right_roms),
        right_only_roms=len(right_roms - left_roms),
        common_roms=len(left_roms & right_roms),
    )


def validate_setup(source: Path | None, dat: Path | None, output: Path | None) -> list[str]:
    issues: list[str] = []
    if not source:
        issues.append("Selecciona una carpeta o archivo origen.")
    elif not source.exists():
        issues.append("El origen seleccionado no existe.")
    if not dat:
        issues.append("Selecciona o importa un DAT.")
    elif not dat.exists():
        issues.append("El DAT seleccionado no existe.")
    else:
        try:
            metadata = inspect_dat(dat, source="validation")
            if metadata.games == 0 or metadata.roms == 0:
                issues.append("El DAT no contiene juegos o ROMs reconocibles.")
        except Exception as exc:
            issues.append(f"No se pudo leer el DAT: {exc}")
    if output and output.exists() and not output.is_dir():
        issues.append("La salida existe pero no es una carpeta.")
    return issues
