from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .models import ActionMode, CandidateDecision, ExportLayout, Manifest, ManifestEntry, OutputBucket, ProfileOutput, ScanResult, ScannedRom, SelectionProfile
from .metadata import parse_no_intro_name
from .platforms import platform_spec
from .ra import RaPatchCandidate, find_ra_patch_candidates


STRICT_1G1R_TAGS = {
    "Anniversary Collection",
    "Aftermarket",
    "Bad",
    "Beta",
    "Castlevania Anniversary Collection",
    "Classic Mini",
    "Contra Anniversary Collection",
    "Demo",
    "Disney Afternoon Collection",
    "Hack",
    "Homebrew",
    "Kiosk",
    "Namcot Collection",
    "Nintendo Switch Online",
    "Overdump",
    "Pirate",
    "Program",
    "Promo",
    "Proto",
    "Prototype",
    "Retro-Bit Generations",
    "Sample",
    "Switch Online",
    "Trainer",
    "Translation",
    "Unl",
    "Unlicensed",
    "Virtual Console",
}

STRICT_1G1R_KEYWORDS = {tag.lower() for tag in STRICT_1G1R_TAGS}

EUROPEAN_REGIONS = {
    "Europe",
    "Spain",
    "France",
    "Germany",
    "Italy",
    "Australia",
    "Netherlands",
    "Sweden",
    "Denmark",
    "Norway",
    "Finland",
    "Portugal",
}

REGION_FOLDERS = {
    "USA": "USA",
    "Japan": "JPN",
    "World": "World",
    "Asia": "Asia",
    "Brazil": "Brazil",
    "China": "China",
    "Korea": "Korea",
    "Taiwan": "Taiwan",
}

SPECIAL_TAG_FOLDERS = {
    "Hack": "Hacks",
    "Trainer": "Hacks",
    "Translation": "Hacks",
    "Unl": "Unlicensed",
    "Unlicensed": "Unlicensed",
    "Pirate": "Unlicensed",
    "Proto": "Prototypes",
    "Prototype": "Prototypes",
    "Beta": "Prototypes",
    "Demo": "Demos",
    "Sample": "Demos",
    "Homebrew": "Homebrew",
    "Aftermarket": "Aftermarket",
    "Bad": "Bad Dumps",
    "Overdump": "Bad Dumps",
}


def _priority_index(values: list[str], priority: list[str]) -> int:
    if not values:
        return len(priority) + 10
    indexes = [priority.index(value) for value in values if value in priority]
    return min(indexes) if indexes else len(priority) + 5


def explain_score(rom: ScannedRom, output: ProfileOutput) -> list[str]:
    region_rank = _priority_index(rom.metadata.regions, output.region_priority)
    language_rank = _priority_index(rom.metadata.languages, output.language_priority)
    revision_label = rom.metadata.version or (str(rom.metadata.revision) if rom.metadata.revision else "unknown")
    reasons = [
        f"Region rank {region_rank}: {', '.join(rom.metadata.regions) or 'unknown'}",
        f"Language rank {language_rank}: {', '.join(rom.metadata.languages) or 'unknown'}",
        f"Revision: {revision_label}",
        "DAT verified" if rom.dat_game else "No DAT match",
    ]
    if rom.ra_game_id:
        reasons.append(f"RA compatible: {rom.ra_title or rom.ra_game_id}")
    if output.prefer_ra_compatible and not output.require_ra:
        reasons.append("RA compatible variants may satisfy main 1G1R")
    return reasons


def _allowed(rom: ScannedRom, output: ProfileOutput) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if output.strict_1g1r and not rom.dat_game:
        return False, ["Excluded by strict 1G1R: no DAT match"]
    strict_excluded = _strict_exclusions(rom) if output.strict_1g1r else []
    if strict_excluded:
        return False, [f"Excluded by strict 1G1R tag: {', '.join(strict_excluded)}"]
    if output.require_ra and not rom.ra_game_id:
        return False, ["No compatible RetroAchievements hash"]
    excluded = [tag for tag in rom.metadata.tags if tag in output.tag_excludes]
    if excluded:
        return False, [f"Excluded by tag: {', '.join(excluded)}"]
    if output.require_ra:
        reasons.append("Compatible with RetroAchievements")
    if output.strict_1g1r:
        reasons.append("Strict 1G1R candidate")
    return True, reasons


def _strict_exclusions(rom: ScannedRom) -> list[str]:
    excluded = {tag for tag in rom.metadata.tags if tag in STRICT_1G1R_TAGS}
    text = " ".join(filter(None, [rom.source_path, rom.inner_path or "", rom.dat_game.name if rom.dat_game else ""])).lower()
    for keyword in STRICT_1G1R_KEYWORDS:
        if keyword in text:
            excluded.add(next(tag for tag in STRICT_1G1R_TAGS if tag.lower() == keyword))
    return sorted(excluded)


def _score(rom: ScannedRom, output: ProfileOutput) -> tuple:
    return (
        _priority_index(rom.metadata.regions, output.region_priority),
        _priority_index(rom.metadata.languages, output.language_priority),
        0 if output.prefer_ra_compatible and rom.ra_game_id else 1,
        -rom.metadata.revision if output.prefer_newest_revision else rom.metadata.revision,
        0 if rom.dat_game else 1,
        rom.source_path.lower(),
    )


def _loss_reasons(rom: ScannedRom, winner: ScannedRom, output: ProfileOutput) -> list[str]:
    rom_region = _priority_index(rom.metadata.regions, output.region_priority)
    winner_region = _priority_index(winner.metadata.regions, output.region_priority)
    if rom_region != winner_region:
        return [
            "Discarded by region priority",
            f"{', '.join(rom.metadata.regions) or 'unknown'} loses to {', '.join(winner.metadata.regions) or 'unknown'}",
        ]

    rom_language = _priority_index(rom.metadata.languages, output.language_priority)
    winner_language = _priority_index(winner.metadata.languages, output.language_priority)
    if rom_language != winner_language:
        return [
            "Discarded by language priority",
            f"{', '.join(rom.metadata.languages) or 'unknown'} loses to {', '.join(winner.metadata.languages) or 'unknown'}",
        ]

    rom_revision = rom.metadata.revision
    winner_revision = winner.metadata.revision
    if output.prefer_ra_compatible and bool(rom.ra_game_id) != bool(winner.ra_game_id):
        return ["Discarded because another candidate covers RetroAchievements"]
    if rom_revision != winner_revision:
        if output.prefer_newest_revision:
            return ["Discarded by older revision", f"Rev {rom_revision} loses to Rev {winner_revision}"]
        return ["Discarded by newer revision", f"Rev {rom_revision} loses to Rev {winner_revision}"]

    if bool(rom.dat_game) != bool(winner.dat_game):
        return ["Discarded because another candidate has DAT verification"]

    return [f"Lower priority than {Path(winner.source_path).name}"]


def _special_folder(rom: ScannedRom) -> str | None:
    for tag in rom.metadata.tags:
        folder = SPECIAL_TAG_FOLDERS.get(tag)
        if folder:
            return folder
    text = " ".join(filter(None, [rom.source_path, rom.inner_path or "", rom.dat_game.name if rom.dat_game else ""])).lower()
    for tag, folder in SPECIAL_TAG_FOLDERS.items():
        if tag.lower() in text:
            return folder
    return None


def _region_folder(rom: ScannedRom, output: ProfileOutput) -> str:
    regions = rom.metadata.regions or (rom.dat_game.releases if rom.dat_game else [])
    if any(region in EUROPEAN_REGIONS for region in regions):
        return "EUR"
    for priority_region in output.region_priority:
        if priority_region in regions:
            return REGION_FOLDERS.get(priority_region, priority_region)
    if regions:
        return REGION_FOLDERS.get(regions[0], regions[0])
    return "Unknown Region"


def _destination_folder(rom: ScannedRom, output: ProfileOutput, layout: ExportLayout) -> Path:
    if layout == ExportLayout.BUCKETS:
        return Path(output.bucket.value)
    special = _special_folder(rom)
    if output.bucket == OutputBucket.RA:
        return Path("Otros") / "RetroAchievements"
    if special:
        return Path("Otros") / special
    return Path(_region_folder(rom, output))


def _destination_path(output_dir: Path | None, rom: ScannedRom, output: ProfileOutput, action: ActionMode, layout: ExportLayout, filename: str | None = None) -> str | None:
    if not output_dir or action == ActionMode.DELETE:
        return None
    return str(output_dir / _destination_folder(rom, output, layout) / (filename or Path(rom.container_path).name))


def _patch_candidate_score(candidate: RaPatchCandidate, output: ProfileOutput) -> tuple:
    metadata = parse_no_intro_name(candidate.hash_name or candidate.title or "")
    return (
        _priority_index(metadata.regions, output.region_priority),
        _priority_index(metadata.languages, output.language_priority),
        -metadata.revision if output.prefer_newest_revision else metadata.revision,
        candidate.hash_name or "",
    )


def _patch_destination_name(candidate: RaPatchCandidate, base: ScannedRom) -> str:
    if candidate.hash_name:
        return Path(candidate.hash_name).name
    return f"{Path(base.container_path).stem} [RA patched]{Path(base.container_path).suffix}"


def select_best(candidates: list[ScannedRom], output: ProfileOutput, override_rom_id: str | None = None) -> tuple[ScannedRom | None, list[CandidateDecision]]:
    decisions: list[CandidateDecision] = []
    allowed: list[ScannedRom] = []
    for rom in candidates:
        ok, reasons = _allowed(rom, output)
        if ok:
            allowed.append(rom)
        else:
            decisions.append(CandidateDecision(rom_id=rom.id, source_path=rom.source_path, kept=False, reasons=reasons))
    if not allowed:
        return None, decisions
    override = next((rom for rom in candidates if rom.id == override_rom_id), None) if override_rom_id else None
    winner = override if override else sorted(allowed, key=lambda rom: _score(rom, output))[0]
    for rom in allowed:
        kept = rom.id == winner.id
        if override and kept:
            reasons = ["Selected by manual override", *explain_score(rom, output)]
        elif kept:
            reasons = ["Selected as best candidate", *explain_score(rom, output)]
        else:
            reasons = [*_loss_reasons(rom, winner, output), *explain_score(rom, output)]
        decisions.append(CandidateDecision(rom_id=rom.id, source_path=rom.source_path, kept=kept, reasons=reasons))
    return winner, decisions


def _groups_for_output(scan: ScanResult, output: ProfileOutput) -> dict[str, list[ScannedRom]]:
    if platform_spec(scan.platform).kind == "arcade":
        return _arcade_groups_for_output(scan, output)
    title_to_parent_keys: dict[str, set[str]] = defaultdict(set)
    for rom in scan.roms:
        title_to_parent_keys[rom.metadata.title].add(rom.dat_game.group_key if rom.dat_game and rom.dat_game.cloneof else rom.metadata.title)

    groups: dict[str, list[ScannedRom]] = defaultdict(list)
    for rom in scan.roms:
        groups[_selection_group_key(rom, title_to_parent_keys)].append(rom)
    return groups


def _arcade_groups_for_output(scan: ScanResult, output: ProfileOutput) -> dict[str, list[ScannedRom]]:
    groups: dict[str, list[ScannedRom]] = defaultdict(list)
    for rom in scan.roms:
        if output.strict_1g1r and rom.dat_game:
            groups[rom.dat_game.group_key].append(rom)
        elif rom.dat_game:
            groups[rom.dat_game.name].append(rom)
        else:
            groups[rom.metadata.title].append(rom)
    return groups


def _selection_group_key(rom: ScannedRom, title_to_parent_keys: dict[str, set[str]]) -> str:
    if len(title_to_parent_keys.get(rom.metadata.title, set())) > 1:
        return rom.metadata.title
    if rom.dat_game and rom.dat_game.cloneof:
        return rom.dat_game.group_key
    return rom.metadata.title


def build_manifest(
    scan: ScanResult,
    profile: SelectionProfile,
    outputs: list[OutputBucket],
    output_dir: Path | None,
    action: ActionMode = ActionMode.COPY,
    overrides: dict[str, dict[str, str]] | None = None,
    ra_cache: Path | None = None,
) -> Manifest:
    manifest = Manifest(
        id=f"manifest-{scan.id}",
        scan_id=scan.id,
        platform=scan.platform,
        profile_snapshot=profile.model_dump(mode="json"),
    )
    selected_paths: set[tuple[OutputBucket, str]] = set()
    copied_main_paths: set[str] = set()
    overrides = overrides or {}
    layout = profile.export_layout
    for output in profile.outputs:
        if output.bucket not in outputs:
            continue
        groups = _groups_for_output(scan, output)
        for group_key, candidates in groups.items():
            override_rom_id = overrides.get(output.bucket.value, {}).get(group_key)
            winner, decisions = select_best(candidates, output, override_rom_id=override_rom_id)
            manifest.discarded.extend(decisions)
            if not winner:
                if output.bucket == OutputBucket.RA and output.require_ra and profile.auto_patch_ra and action != ActionMode.DELETE:
                    base_output = output.model_copy(update={"require_ra": False})
                    base_winner, base_decisions = select_best(candidates, base_output, override_rom_id=override_rom_id)
                    manifest.discarded.extend(base_decisions)
                    if base_winner:
                        patch_candidates = sorted(find_ra_patch_candidates(scan.platform, base_winner.metadata.title, cache=ra_cache), key=lambda candidate: _patch_candidate_score(candidate, output))
                        if patch_candidates:
                            patch_candidate = patch_candidates[0]
                            destination_name = _patch_destination_name(patch_candidate, base_winner)
                            destination = _destination_path(output_dir, base_winner, output, action, layout, filename=destination_name)
                            manifest.entries.append(
                                ManifestEntry(
                                    bucket=output.bucket,
                                    action=action,
                                    source_path=base_winner.container_path,
                                    source_inner_path=base_winner.inner_path,
                                    destination_path=destination,
                                    rom_id=base_winner.id,
                                    dat_name=base_winner.dat_game.name if base_winner.dat_game else None,
                                    ra_game_id=patch_candidate.game_id,
                                    patch_url=patch_candidate.patch_url,
                                    patch_expected_md5=patch_candidate.md5,
                                    patch_name=patch_candidate.hash_name,
                                    explanation=[
                                        "RetroAchievements output generated by patch",
                                        f"Patch URL: {patch_candidate.patch_url}",
                                        f"Expected RA MD5: {patch_candidate.md5}",
                                        f"Organized export folder: {_destination_folder(base_winner, output, layout)}",
                                        *explain_score(base_winner, base_output),
                                    ],
                                )
                            )
                continue
            if layout == ExportLayout.ORGANIZED and output.bucket == OutputBucket.RA and winner.container_path in copied_main_paths:
                continue
            key = (output.bucket, winner.container_path)
            if key in selected_paths:
                continue
            selected_paths.add(key)
            if output.bucket == OutputBucket.MAIN:
                copied_main_paths.add(winner.container_path)
            destination = _destination_path(output_dir, winner, output, action, layout)
            explanation = ["Selected by manual override"] if override_rom_id == winner.id else ["Selected as best candidate"]
            if layout == ExportLayout.ORGANIZED:
                explanation.append(f"Organized export folder: {_destination_folder(winner, output, layout)}")
            if output.require_ra:
                explanation.append("RetroAchievements output requires a matching RA hash")
            if winner.ra_patch_url or "rapatches" in {label.lower() for label in winner.ra_labels}:
                explanation.append(f"RetroAchievements patch metadata: {winner.ra_patch_url or 'rapatches'}")
            if winner.dat_game:
                explanation.append(f"DAT match: {winner.dat_game.name}")
            explanation.extend(explain_score(winner, output))
            manifest.entries.append(
                ManifestEntry(
                    bucket=output.bucket,
                    action=action,
                    source_path=winner.container_path,
                    destination_path=destination,
                    rom_id=winner.id,
                    dat_name=winner.dat_game.name if winner.dat_game else None,
                    ra_game_id=winner.ra_game_id,
                    explanation=explanation,
                )
            )
    return manifest
