"""Filas de decisiones, manifiesto y perfiles de selección de la GUI."""
from __future__ import annotations

from pathlib import Path

from ..diagnostics import build_patch_queue
from ..metadata import with_part
from ..models import ExportLayout, OutputBucket, ProfileOutput, ScannedRom, SelectionProfile
from ..profile import list_profiles

REGIONS = ["Spain", "Europe", "World", "USA", "Japan", "Asia", "Brazil", "China", "Korea"]


LANGUAGES = ["Spanish", "English", "Multi", "Japanese", "French", "German", "Italian", "Portuguese"]


TAGS = ["Beta", "Proto", "Prototype", "Demo", "Sample", "Aftermarket", "Homebrew", "Unl", "Pirate", "Hack", "Bad", "Overdump"]


def _rom_summary_key(rom) -> str:
    # El soporte tiene que ir en la clave igual que en rules._selection_group_key:
    # si no, el override manual de un disco no casa con su grupo del manifiesto.
    base = rom.dat_game.group_key if rom.dat_game and rom.dat_game.cloneof else rom.metadata.title
    return with_part(base, rom.metadata.part)


def _scan_group_sample(scan, limit: int):
    if scan is None:
        return None
    seen: set[str] = set()
    selected: set[str] = set()
    for rom in sorted(scan.roms, key=lambda item: (_rom_summary_key(item).lower(), item.source_path.lower())):
        key = _rom_summary_key(rom)
        if key not in seen:
            seen.add(key)
            selected.add(key)
        if len(selected) >= limit:
            break
    sample = scan.model_copy(deep=True)
    sample.roms = [rom for rom in sample.roms if _rom_summary_key(rom) in selected]
    sample.unmatched_files = []
    return sample


def _profile_from_controls(controls: dict[str, object]) -> SelectionProfile:
    outputs: list[ProfileOutput] = []
    if controls["main_enabled"].value:  # type: ignore[attr-defined]
        outputs.append(
            ProfileOutput(
                bucket=OutputBucket.MAIN,
                require_ra=controls["main_require_ra"].value,  # type: ignore[attr-defined]
                strict_1g1r=controls["main_strict_1g1r"].value,  # type: ignore[attr-defined]
                prefer_ra_compatible=controls["main_prefer_ra"].value,  # type: ignore[attr-defined]
                region_priority=list(controls["main_regions"].value),  # type: ignore[attr-defined]
                language_priority=list(controls["main_languages"].value),  # type: ignore[attr-defined]
                tag_excludes=list(controls["main_tags"].value),  # type: ignore[attr-defined]
                prefer_newest_revision=controls["main_newest"].value,  # type: ignore[attr-defined]
            )
        )
    if controls["ra_enabled"].value:  # type: ignore[attr-defined]
        outputs.append(
            ProfileOutput(
                bucket=OutputBucket.RA,
                require_ra=True,
                strict_1g1r=controls["ra_strict_1g1r"].value,  # type: ignore[attr-defined]
                region_priority=list(controls["ra_regions"].value),  # type: ignore[attr-defined]
                language_priority=list(controls["ra_languages"].value),  # type: ignore[attr-defined]
                tag_excludes=list(controls["ra_tags"].value),  # type: ignore[attr-defined]
                prefer_newest_revision=controls["ra_newest"].value,  # type: ignore[attr-defined]
            )
        )
    return SelectionProfile(
        name=controls["profile_name"].value or "custom",  # type: ignore[attr-defined]
        export_layout=ExportLayout(controls["export_layout"].value),  # type: ignore[attr-defined]
        auto_patch_ra=controls["auto_patch_ra"].value,  # type: ignore[attr-defined]
        outputs=outputs,
    )


def _profile_options() -> dict[str, str]:
    return {str(path): name for name, path in list_profiles().items()}


def _apply_profile_to_controls(profile: SelectionProfile, controls: dict[str, object]) -> None:
    controls["profile_name"].value = profile.name  # type: ignore[attr-defined]
    controls["export_layout"].value = profile.export_layout.value  # type: ignore[attr-defined]
    controls["auto_patch_ra"].value = profile.auto_patch_ra  # type: ignore[attr-defined]
    outputs = {output.bucket: output for output in profile.outputs}
    main = outputs.get(OutputBucket.MAIN, ProfileOutput(bucket=OutputBucket.MAIN))
    ra = outputs.get(OutputBucket.RA, ProfileOutput(bucket=OutputBucket.RA, require_ra=True))
    controls["main_enabled"].value = OutputBucket.MAIN in outputs  # type: ignore[attr-defined]
    controls["main_require_ra"].value = main.require_ra  # type: ignore[attr-defined]
    controls["main_strict_1g1r"].value = main.strict_1g1r  # type: ignore[attr-defined]
    controls["main_prefer_ra"].value = main.prefer_ra_compatible  # type: ignore[attr-defined]
    controls["main_regions"].value = main.region_priority  # type: ignore[attr-defined]
    controls["main_languages"].value = main.language_priority  # type: ignore[attr-defined]
    controls["main_tags"].value = main.tag_excludes  # type: ignore[attr-defined]
    controls["main_newest"].value = main.prefer_newest_revision  # type: ignore[attr-defined]
    controls["ra_enabled"].value = OutputBucket.RA in outputs  # type: ignore[attr-defined]
    controls["ra_strict_1g1r"].value = ra.strict_1g1r  # type: ignore[attr-defined]
    controls["ra_regions"].value = ra.region_priority  # type: ignore[attr-defined]
    controls["ra_languages"].value = ra.language_priority  # type: ignore[attr-defined]
    controls["ra_tags"].value = ra.tag_excludes  # type: ignore[attr-defined]
    controls["ra_newest"].value = ra.prefer_newest_revision  # type: ignore[attr-defined]


def _entry_reasons_by_rom(manifest) -> dict[str, list[str]]:
    reasons: dict[str, list[str]] = {}
    if not manifest:
        return reasons
    for entry in manifest.entries:
        reasons.setdefault(entry.rom_id, []).extend(entry.explanation)
    return reasons


def _discard_reasons_by_rom(manifest) -> dict[str, list[str]]:
    reasons: dict[str, list[str]] = {}
    if not manifest:
        return reasons
    for decision in manifest.discarded:
        if not decision.kept:
            reasons.setdefault(decision.rom_id, []).extend(decision.reasons)
    return reasons


def _entry_reasons_for_group(scan, manifest, group_key: str) -> list[str]:
    if scan is None or manifest is None:
        return []
    rom_by_id = {rom.id: rom for rom in scan.roms}
    reasons: list[str] = []
    for entry in manifest.entries:
        rom = rom_by_id.get(entry.rom_id)
        if rom and _rom_summary_key(rom) == group_key:
            reasons.extend(entry.explanation)
    return reasons


def _discard_reasons_for_group(scan, manifest, group_key: str) -> list[str]:
    if scan is None or manifest is None:
        return []
    rom_by_id = {rom.id: rom for rom in scan.roms}
    reasons: list[str] = []
    for decision in manifest.discarded:
        rom = rom_by_id.get(decision.rom_id)
        if rom and _rom_summary_key(rom) == group_key and not decision.kept:
            reasons.extend(decision.reasons)
    return reasons


def _decision_detail(reasons: list[str], fallback: str) -> str:
    if not reasons:
        return fallback
    text = " ".join(reasons).lower()
    labels: list[str] = []
    if "manual override" in text:
        labels.append("🎯 override")
    if "strict 1g1r" in text:
        labels.append("🎮 1G1R")
    if "no compatible retroachievements" in text:
        labels.append("🏆 sin RA")
    elif "retroachievements" in text or "ra compatible" in text:
        labels.append("🏆 RA")
    if "patch metadata" in text or "rapatches" in text or "generated by patch" in text or "patch url" in text:
        labels.append("🩹 parche")
    if "excluded by tag" in text:
        labels.append("🏷️ tag excluido")
    if "no dat match" in text:
        labels.append("❌ sin DAT")
    if "region priority" in text or "region rank" in text:
        labels.append("🌍 región")
    if "language priority" in text or "language rank" in text:
        labels.append("💬 idioma")
    if "revision" in text:
        labels.append("🔢 revisión")
    positive_dat = "dat verified" in text or "dat match:" in text or "another candidate has dat" in text
    if positive_dat:
        labels.append("✅ DAT")
    if "lower priority" in text:
        labels.append("🔁 mejor variante")
    if "selected as best" in text:
        labels.append("⭐ mejor")
    return " · ".join(dict.fromkeys(labels)) or fallback


def _output_detail(scan, manifest, group_key: str, main: bool, ra: bool) -> str:
    fallback = _output_label(main, ra)
    if scan is None or manifest is None:
        return fallback
    rom_by_id = {rom.id: rom for rom in scan.roms}
    parts: list[str] = []
    seen_files: dict[str, str] = {}
    for entry in manifest.entries:
        rom = rom_by_id.get(entry.rom_id)
        if not rom or _rom_summary_key(rom) != group_key:
            continue
        filename = Path(entry.source_path).name
        if filename in seen_files.values():
            parts.append(f"{entry.bucket.value}: mismo")
        else:
            parts.append(f"{entry.bucket.value}: {filename}")
        seen_files[entry.bucket.value] = filename
    return " · ".join(parts) or fallback


def _output_label(main: bool, ra: bool) -> str:
    outputs = []
    if main:
        outputs.append("main")
    if ra:
        outputs.append("RA")
    return ", ".join(outputs) or "Plan no creado"


def _variant_visual(kind: str) -> str:
    if kind in {"keep", "matched"}:
        return "green"
    if kind == "drop":
        return "yellow"
    if kind in {"missing_romset", "outside_dat"}:
        return "red"
    return "neutral"


def _variant_status(in_dat: bool, will_keep_main: bool, will_keep_ra: bool, planned: bool) -> str:
    if will_keep_main or will_keep_ra:
        return "Se guardará"
    if in_dat and planned:
        return "Se perderá"
    if in_dat:
        return "Coincide con DAT"
    return "Fuera del DAT"


def _plan_reason_icons(explanations: list[str]) -> str:
    text = " ".join(explanations).lower()
    icons: list[str] = []
    if "manual override" in text:
        icons.append("🎯 override")
    if "strict 1g1r" in text:
        icons.append("🎮 1G1R")
    if "dat match:" in text or "dat verified" in text:
        icons.append("✅ DAT")
    if "retroachievements" in text or "ra compatible" in text:
        icons.append("🏆 RA")
    if "patch metadata" in text or "rapatches" in text or "generated by patch" in text or "patch url" in text:
        icons.append("🩹 parche")
    if "region rank" in text or "region priority" in text:
        icons.append("🌍 región")
    if "language rank" in text or "language priority" in text:
        icons.append("💬 idioma")
    if "revision" in text:
        icons.append("🔢 revisión")
    return " · ".join(dict.fromkeys(icons)) or "ℹ️"


def _bucket_divergence_rows(scan, manifest) -> list[dict[str, str]]:
    if scan is None or manifest is None:
        return []
    rom_by_id = {rom.id: rom for rom in scan.roms}
    grouped: dict[str, dict[str, str]] = {}
    for entry in manifest.entries:
        rom = rom_by_id.get(entry.rom_id)
        key = _rom_summary_key(rom) if rom else (entry.dat_name or entry.rom_id)
        grouped.setdefault(key, {})[entry.bucket.value] = entry.source_path
    rows = []
    for key, buckets in sorted(grouped.items(), key=lambda item: item[0].lower()):
        main = buckets.get("main", "")
        ra = buckets.get("ra", "")
        rows.append(
            {
                "game": key,
                "main": Path(main).name if main else "",
                "ra": Path(ra).name if ra else "",
                "state": "mismo archivo" if main and ra and main == ra else ("distinto" if main and ra else "solo una salida"),
            }
        )
    return rows


def _export_tree_rows(manifest, output_root: str | None) -> list[dict[str, str | int]]:
    if manifest is None:
        return []
    grouped: dict[str, dict[str, str | int]] = {}
    root = Path(output_root) if output_root else None
    for entry in manifest.entries:
        if not entry.destination_path:
            folder = "[sin destino]"
        elif root:
            try:
                folder = str(Path(entry.destination_path).parent.relative_to(root)) or "."
            except ValueError:
                folder = str(Path(entry.destination_path).parent)
        else:
            folder = str(Path(entry.destination_path).parent)
        row = grouped.setdefault(folder, {"folder": folder, "files": 0, "main": 0, "ra": 0, "patches": 0})
        row["files"] = int(row["files"]) + 1
        row[entry.bucket.value] = int(row.get(entry.bucket.value, 0)) + 1
        if entry.patch_url:
            row["patches"] = int(row["patches"]) + 1
    return sorted(grouped.values(), key=lambda row: str(row["folder"]).lower())


def _ra_conflict_rows(scan, manifest) -> list[dict[str, str]]:
    if scan is None:
        return []
    manifest = manifest or None
    rom_by_id = {rom.id: rom for rom in scan.roms}
    main_by_group: dict[str, ScannedRom] = {}
    ra_by_group: dict[str, ScannedRom] = {}
    if manifest:
        for entry in manifest.entries:
            rom = rom_by_id.get(entry.rom_id)
            if not rom:
                continue
            key = _rom_summary_key(rom)
            if entry.bucket == OutputBucket.MAIN:
                main_by_group[key] = rom
            elif entry.bucket == OutputBucket.RA:
                ra_by_group[key] = rom
    grouped: dict[str, list] = {}
    for rom in scan.roms:
        grouped.setdefault(_rom_summary_key(rom), []).append(rom)
    rows: list[dict[str, str]] = []
    for key, roms in sorted(grouped.items(), key=lambda item: item[0].lower()):
        main_rom = main_by_group.get(key)
        ra_rom = ra_by_group.get(key)
        ra_candidates = [rom for rom in roms if rom.ra_game_id]
        if main_rom and not main_rom.ra_game_id and ra_candidates:
            best_ra = ra_rom or sorted(ra_candidates, key=lambda rom: (rom.metadata.revision, rom.source_path.lower()))[-1]
            rows.append(
                {
                    "game": key,
                    "main": Path(main_rom.container_path).name,
                    "ra": Path(best_ra.container_path).name,
                    "state": "main sin RA; existe variante RA",
                }
            )
        elif main_rom and main_rom.ra_game_id:
            rows.append(
                {
                    "game": key,
                    "main": Path(main_rom.container_path).name,
                    "ra": "",
                    "state": "main ya cubre RA",
                }
            )
    return rows


def _patch_queue_rows(manifest) -> list[dict[str, str]]:
    return [
        {
            "status": row.status,
            "game": row.game,
            "source": row.source,
            "patch": row.patch,
            "expected": row.expected_md5,
            "destination": row.destination,
        }
        for row in build_patch_queue(manifest)
    ]
