"""Estado global de la GUI y helpers que dependen de él."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from .coverage import CoverageSummary
from .dat_sources import list_dat_sources
from .gui_rows import _decision_detail, _flag_regions, _ra_icon, _rom_summary_key
from .models import ActionMode, DatCatalog, Manifest, OutputBucket, Platform, ProfileOutput, ScanResult, SelectionProfile
from .profile import DEFAULT_PROFILE, list_recommended_profiles
from .rules import build_manifest, explain_score


# Estado global de la aplicación: RetroPerfect es una herramienta local
# mono-usuario; todas las pestañas del navegador comparten este estado.
@dataclass
class AppState:
    platform: Platform = Platform.NES
    scan: ScanResult | None = None
    manifest: Manifest | None = None
    profile: SelectionProfile = field(default_factory=lambda: DEFAULT_PROFILE.model_copy(deep=True))
    catalog: DatCatalog | None = None
    coverage: CoverageSummary | None = None
    overrides: dict[str, dict[str, str]] = field(default_factory=lambda: {"main": {}, "ra": {}})
    setup_ready: bool = False
    suppress_setup_dirty: bool = False
    scan_progress: dict[str, Any] = field(default_factory=lambda: {"current": 0, "total": 0, "path": "", "roms": 0, "matched": 0, "phase": "idle"})
    ra_details_progress: dict[str, Any] = field(default_factory=lambda: {"current": 0, "total": 0, "updated": 0, "running": False})
    dark_mode: bool = False
    activity: list[dict[str, str]] = field(default_factory=list)


state = AppState()



def reset_state() -> None:
    """Restablece el estado global (usado por los tests)."""
    fresh = AppState()
    for item in fields(AppState):
        setattr(state, item.name, getattr(fresh, item.name))


def _current_platform() -> Platform:
    return Platform(state.platform)


def _log_activity(message: str, level: str = "INFO") -> None:
    rows = list(state.activity)
    rows.insert(
        0,
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        },
    )
    state.activity = rows[:200]


def _activity_rows() -> list[dict[str, str]]:
    return list(state.activity)


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
                overrides=state.overrides,  # type: ignore[arg-type]
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


def _group_rows(scan) -> list[dict[str, str | int]]:
    if scan is None:
        return []
    grouped: dict[str, list] = {}
    for rom in scan.roms:
        grouped.setdefault(_rom_summary_key(rom), []).append(rom)
    rows = []
    overrides = state.overrides
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
    main_override = state.overrides.get("main", {}).get(group_key)  # type: ignore[union-attr]
    ra_override = state.overrides.get("ra", {}).get(group_key)  # type: ignore[union-attr]
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
