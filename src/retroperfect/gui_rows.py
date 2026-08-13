"""Constructores de filas y formateadores puros de la GUI (sin estado ni widgets)."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .dat_manager import list_installed_dats
from .dat_sources import DAT_SOURCES
from .diagnostics import build_patch_queue
from .models import ActionMode, ExportLayout, OutputBucket, Platform, ProfileOutput, ScannedRom, SelectionProfile
from .paths import project_state_dir
from .platforms import list_platforms, platform_spec
from .profile import list_profiles
from .ra import ra_cache_count, ra_sync_status

REGIONS = ["Spain", "Europe", "World", "USA", "Japan", "Asia", "Brazil", "China", "Korea"]


LANGUAGES = ["Spanish", "English", "Multi", "Japanese", "French", "German", "Italian", "Portuguese"]


TAGS = ["Beta", "Proto", "Prototype", "Demo", "Sample", "Aftermarket", "Homebrew", "Unl", "Pirate", "Hack", "Bad", "Overdump"]


ACTION_LABELS = {
    ActionMode.COPY.value: "Copiar archivos",
    ActionMode.MOVE.value: "Mover archivos",
    ActionMode.DELETE.value: "Borrar archivos",
}


def _source_suffixes() -> set[str]:
    suffixes = {".zip"}
    for spec in list_platforms():
        suffixes.update(spec.rom_extensions)
    return suffixes


def _page_class() -> str:
    return "max-w-screen-2xl mx-auto w-full px-4 py-4"


def _panel_class() -> str:
    return "rp-panel border border-gray-200 rounded-md p-4 w-full"


def _latest_project_path() -> Path:
    return project_state_dir() / "project.json"


def _unmatched_rows(scan) -> list[dict[str, str | int]]:
    if scan is None:
        return []
    rows: list[dict[str, str | int]] = []
    for rom in scan.roms:
        if rom.dat_game:
            continue
        file_label = Path(rom.container_path).name if not rom.inner_path else f"{Path(rom.container_path).name} / {rom.inner_path}"
        rows.append(
            {
                "type": "Hash fuera del DAT",
                "file": file_label,
                "region": _flag_regions(rom.metadata.regions),
                "size": rom.hashes.size,
                "md5": rom.hashes.md5[:12],
                "suggestion": "Comprueba variante del DAT: headered/unheadered, endian, A78/BIN o plataforma equivocada.",
            }
        )
    for path in scan.unmatched_files:
        rows.append(
            {
                "type": "Archivo no procesado",
                "file": Path(path).name,
                "region": "",
                "size": "",
                "md5": "",
                "suggestion": "Extensión no soportada, ZIP sin ROM válida o archivo corrupto.",
            }
        )
    return rows


def _duplicate_rows(scan) -> list[dict[str, str | int]]:
    if scan is None:
        return []
    rows: list[dict[str, str | int]] = []
    by_hash: dict[str, list] = defaultdict(list)
    by_game: dict[str, list] = defaultdict(list)
    for rom in scan.roms:
        by_hash[rom.hashes.md5].append(rom)
        by_game[_rom_summary_key(rom)].append(rom)
    for md5, roms in sorted(by_hash.items(), key=lambda item: item[0]):
        paths = sorted({Path(rom.container_path).name for rom in roms})
        if len(paths) <= 1:
            continue
        rows.append(
            {
                "kind": "Hash idéntico",
                "game": roms[0].metadata.title,
                "count": len(paths),
                "detail": f"{md5[:12]} · " + " · ".join(paths[:4]),
            }
        )
    for game, roms in sorted(by_game.items(), key=lambda item: item[0].lower()):
        paths = sorted({Path(rom.container_path).name for rom in roms})
        regions = sorted({region for rom in roms for region in rom.metadata.regions})
        if len(paths) <= 1:
            continue
        rows.append(
            {
                "kind": "Variantes 1G1R",
                "game": game,
                "count": len(paths),
                "detail": f"{_flag_regions(regions)} · " + " · ".join(paths[:4]),
            }
        )
    return rows[:500]


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


def _direct_dat_batch_candidates(scope: str, platform: Platform, limit: int) -> list[str]:
    sources = [
        source
        for source in DAT_SOURCES
        if source.direct_download and (scope == "all" or source.platform == platform.value)
    ]
    seen: set[str] = set()
    selected: list[str] = []
    for source in sources:
        if source.platform in seen:
            continue
        seen.add(source.platform)
        selected.append(source.id)
        if len(selected) >= limit:
            break
    return selected


DATOMATIC_GAP_ROWS = [
    {"group": "Ordenadores", "platform": "Fujitsu FM Towns, FM-7, FMR50; Luxor ABC 800; Atari ST Tapes", "status": "Pendiente"},
    {"group": "Portátiles/raras", "platform": "GamePark GP2X/GP2X Digital, Hartung Game Master, Funtech Super Acan, Konami Picno, LeapPad/My First LeapPad, LeapFrog Explorer", "status": "Pendiente"},
    {"group": "Nintendo variantes", "platform": "GBA Multiboot/Video, GameCube NPDP Carts, Switch Dev ROMs, 3DS SpotPass, Wii U CDN Dev/Lotcheck, Wii deprecated split DLC, Wii Dev/Starlight", "status": "Parcial"},
    {"group": "Sony variantes", "platform": "PS3 DLC/Updates/Avatars/Themes/SingStore, PS4 Avatars/Updates, PlayStation Mobile, Vita Updates, UMD Music/Video, PS5 Non-Redump", "status": "Parcial"},
    {"group": "Microsoft variantes", "platform": "Xbox Development Kit Hard Drives, Xbox 360 Development Kit Hard Drives, Xbox 360 Digital variantes finas", "status": "Parcial"},
    {"group": "PC/digital", "platform": "IBM PC digital stores, Android stores, J2ME, Palm OS, Pocket PC, Symbian", "status": "No implementado"},
    {"group": "Nuevos/aislados", "platform": "Blaze Evercade, Hitachi S1, Software Preservation Society marcados como fuente externa", "status": "Pendiente"},
    {"group": "Preservación", "platform": "Source Code DATs, Magazine Scans, zTEST", "status": "No operativo"},
    {"group": "Non-Redump especiales", "platform": "Audio CD, DVD-Video, Super Audio CD, PC Compatible Discs Hentai", "status": "Parcial/manual"},
]


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


def _coverage_rows(summary, mode: str, scan=None, manifest=None) -> list[dict[str, str | int]]:
    rows = summary.rows
    if mode == "missing":
        rows = [row for row in rows if row.in_dat and not row.in_romset]
    elif mode == "unmatched":
        rows = [row for row in rows if row.in_romset and not row.in_dat]
    elif mode == "hash_mismatch":
        rows = [row for row in rows if row.in_dat and row.in_romset and not row.matched]
    elif mode == "matched":
        rows = [row for row in rows if row.matched]
    elif mode == "will_drop":
        rows = [row for row in rows if row.will_drop_all]
    elif mode == "complete_any_region":
        rows = [row for row in rows if row.in_dat and row.in_romset]
    return [
        {
            "title": row.title,
            "visual": _coverage_visual(row),
            "status": _coverage_status(row),
            "variants": f"DAT {row.dat_variants} · ROM {row.rom_variants} · Match {row.matched_variants}",
            "ra": "🏆" if row.ra_variants else "",
            "dat_regions": _flag_regions(row.dat_regions),
            "rom_regions": _flag_regions(row.rom_regions),
            "keep": _output_detail(scan, manifest, row.group_key, row.will_keep_main, row.will_keep_ra),
            "reason": _coverage_reason(row, scan, manifest),
            "kind": _coverage_kind(row),
        }
        for row in rows
    ]


def _coverage_variant_rows(scan, catalog, manifest, mode: str) -> list[dict[str, str | int]]:
    if scan is None:
        return []
    kept: dict[str, set[str]] = {}
    if manifest:
        for entry in manifest.entries:
            kept.setdefault(entry.rom_id, set()).add(entry.bucket.value)
    kept_reasons = _entry_reasons_by_rom(manifest)
    discard_reasons = _discard_reasons_by_rom(manifest)
    roms_by_dat_name: dict[str, list] = {}
    unmatched_roms = []
    for rom in scan.roms:
        if rom.dat_game:
            roms_by_dat_name.setdefault(rom.dat_game.name, []).append(rom)
        else:
            unmatched_roms.append(rom)
    rows = []
    if catalog:
        for game in catalog.games:
            roms = roms_by_dat_name.get(game.name, [])
            if roms:
                for rom in roms:
                    will_keep_main = "main" in kept.get(rom.id, set())
                    will_keep_ra = "ra" in kept.get(rom.id, set())
                    if will_keep_main or will_keep_ra:
                        kind = "keep"
                    elif manifest:
                        kind = "drop"
                    else:
                        kind = "matched"
                    rows.append(
                        {
                            "title": rom.metadata.title,
                            "visual": _variant_visual(kind),
                            "status": _variant_status(True, will_keep_main, will_keep_ra, bool(manifest)),
                            "variants": Path(rom.container_path).name if not rom.inner_path else f"{Path(rom.container_path).name} / {rom.inner_path}",
                            "ra": _ra_icon(rom),
                            "dat_regions": _flag_regions(game.releases),
                            "rom_regions": _flag_regions(rom.metadata.regions),
                            "keep": _output_label(will_keep_main, will_keep_ra),
                            "reason": _decision_detail(
                                kept_reasons.get(rom.id, []) if will_keep_main or will_keep_ra else discard_reasons.get(rom.id, []),
                                fallback="✅ DAT confirmado" if not manifest else "🔁 Pierde contra otra variante",
                            ),
                            "kind": kind,
                        }
                    )
            else:
                rows.append(
                    {
                        "title": game.description or game.name,
                        "visual": "red",
                        "status": "Falta en romset",
                        "variants": game.roms[0].name if game.roms else game.name,
                        "ra": "",
                        "dat_regions": _flag_regions(game.releases),
                        "rom_regions": "",
                        "keep": "No disponible",
                        "reason": "📭 Falta archivo",
                        "kind": "missing_romset",
                    }
                )
    else:
        unmatched_roms = list(scan.roms)
    for rom in unmatched_roms:
        rows.append(
            {
                "title": rom.metadata.title,
                "visual": "red",
                "status": "Fuera del DAT",
                "variants": Path(rom.container_path).name if not rom.inner_path else f"{Path(rom.container_path).name} / {rom.inner_path}",
                "ra": _ra_icon(rom),
                "dat_regions": "",
                "rom_regions": _flag_regions(rom.metadata.regions),
                "keep": "No disponible",
                "reason": "❌ Sin match DAT",
                "kind": "outside_dat",
            }
        )
    if mode == "matched":
        rows = [row for row in rows if row["kind"] in {"matched", "keep", "drop"}]
    elif mode == "unmatched":
        rows = [row for row in rows if row["kind"] == "outside_dat"]
    elif mode == "will_drop":
        rows = [row for row in rows if row["kind"] == "drop"]
    elif mode == "missing":
        rows = [row for row in rows if row["kind"] == "missing_romset"]
    elif mode == "hash_mismatch":
        rows = [row for row in rows if row["kind"] == "hash_mismatch"]
    elif mode == "complete_any_region":
        rows = [row for row in rows if row["kind"] in {"matched", "keep", "drop"}]
    return rows


def _coverage_kind(row) -> str:
    if row.in_dat and not row.in_romset:
        return "missing_romset"
    if row.in_romset and not row.in_dat:
        return "outside_dat"
    if row.in_dat and row.in_romset and not row.matched:
        return "hash_mismatch"
    if row.will_keep_main or row.will_keep_ra:
        return "keep"
    if row.will_drop_all:
        return "drop"
    if row.matched:
        return "matched"
    return "neutral"


def _coverage_status(row) -> str:
    if row.matched:
        if row.will_keep_main or row.will_keep_ra:
            return "Se guardará"
        if row.will_drop_all:
            return "Se perderá"
        return "Coincide con DAT"
    if row.in_dat and not row.in_romset:
        return "Falta en romset"
    if row.in_romset and not row.in_dat:
        return "Fuera del DAT"
    if row.in_dat and row.in_romset and not row.matched:
        return "Sin match exacto"
    if row.will_drop_all:
        return "Se perderá"
    return "Pendiente"


def _coverage_visual(row) -> str:
    if (row.in_dat and not row.in_romset) or (row.in_romset and not row.in_dat) or (row.in_dat and row.in_romset and not row.matched):
        return "red"
    if row.will_keep_main or row.will_keep_ra:
        return "green"
    if row.will_drop_all:
        return "yellow"
    if row.matched:
        return "green"
    return "neutral"


def _coverage_reason(row, scan=None, manifest=None) -> str:
    if row.in_dat and not row.in_romset:
        return "📭 Falta archivo"
    if row.in_romset and not row.matched:
        if row.in_dat:
            return "🧬 Hash distinto"
        return "❌ Sin match DAT"
    if row.will_keep_main or row.will_keep_ra:
        reasons = _entry_reasons_for_group(scan, manifest, row.group_key)
        return _decision_detail(reasons, fallback=f"📦 Salida {', '.join(bucket for bucket, active in [('main', row.will_keep_main), ('ra', row.will_keep_ra)] if active)}")
    if row.will_drop_all:
        reasons = _discard_reasons_for_group(scan, manifest, row.group_key)
        return _decision_detail(reasons, fallback="🔁 Perfil descarta variantes")
    if row.matched:
        return "✅ DAT confirmado"
    return row.missing_reason


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


def _rom_summary_key(rom) -> str:
    if rom.dat_game and rom.dat_game.cloneof:
        return rom.dat_game.group_key
    return rom.metadata.title


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


def _output_label(main: bool, ra: bool) -> str:
    outputs = []
    if main:
        outputs.append("main")
    if ra:
        outputs.append("RA")
    return ", ".join(outputs) or "Plan no creado"


FLAGS = {
    "Spain": "🇪🇸",
    "Europe": "🇪🇺",
    "USA": "🇺🇸",
    "Japan": "🇯🇵",
    "World": "🌐",
    "Asia": "🌏",
    "Brazil": "🇧🇷",
    "China": "🇨🇳",
    "Korea": "🇰🇷",
    "Germany": "🇩🇪",
    "France": "🇫🇷",
    "Italy": "🇮🇹",
    "Australia": "🇦🇺",
    "Taiwan": "🇹🇼",
}


def _flag_regions(regions: list[str]) -> str:
    return ", ".join(f"{FLAGS.get(region, '🏳️')} {region}" for region in regions)


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


def _ra_icon(rom) -> str:
    if not rom.ra_game_id:
        return ""
    icons = ["🏆"]
    if rom.ra_patch_url or "rapatches" in {label.lower() for label in rom.ra_labels}:
        icons.append("🩹")
    return " ".join(icons)


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


def _dat_rows(platform: Platform | None = None) -> list[dict[str, str | int]]:
    dats = list_installed_dats()
    if platform is not None:
        dats = [dat for dat in dats if dat.platform in {None, platform.value}]
    return [
        {
            "id": dat.id,
            "name": dat.name,
            "platform": platform_spec(dat.platform).short_name if dat.platform else "Sin detectar",
            "source": dat.source,
            "format": dat.format,
            "games": dat.games,
            "roms": dat.roms,
            "pc": "sí" if dat.parent_clone else "no",
            "header": dat.header_mode,
            "recommended": "sí" if dat.recommended else "no",
            "regions": ", ".join(dat.regions[:8]),
            "path": dat.path,
            "notes": dat.notes,
        }
        for dat in dats
    ]


def _platform_card_rows(brand: str = "Todas", kind: str = "Todos", generation: str = "Todas") -> list[dict[str, str]]:
    specs = list_platforms()
    if brand != "Todas":
        specs = [spec for spec in specs if spec.brand == brand]
    if kind != "Todos":
        specs = [spec for spec in specs if spec.kind == kind]
    if generation != "Todas":
        specs = [spec for spec in specs if spec.generation == generation]
    return [
        {
            "id": spec.id.value,
            "icon": spec.icon,
            "icon_url": spec.icon_url or "",
            "name": spec.short_name,
            "brand": spec.brand,
            "generation": spec.generation,
            "kind": spec.kind,
            "extensions": spec.extension_label,
            "dat": spec.dat_recommended,
            "romset": spec.romset_recommended,
            "tip": spec.collection_tip,
            "ra": spec.ra_label,
            "complexity": spec.complexity,
            "notes": spec.notes,
        }
        for spec in specs
    ]


def _platform_tab_matches(spec, tab: str) -> bool:
    if tab == "Todas":
        return True
    if tab in {"Nintendo", "Sega", "Atari", "NEC", "Sony", "Microsoft", "Apple", "Commodore"}:
        return spec.brand == tab
    if tab == "Arcade":
        return spec.kind == "arcade" or spec.brand == "Arcade"
    if tab == "SNK/Bandai":
        return spec.brand in {"SNK", "Bandai"}
    if tab == "Discos/Digital":
        return spec.kind in {"disco", "digital"}
    if tab == "Ordenadores":
        return spec.kind == "ordenador"
    if tab == "Otras":
        return spec.brand == "Otros" and spec.kind not in {"experimental", "ordenador", "arcade"} and spec.complexity != "experimental"
    if tab == "Especiales":
        return spec.kind in {"experimental"} or spec.complexity == "experimental"
    return True


def _platform_card_rows_for_tab(tab: str, kind: str = "Todos", generation: str = "Todas", query: str = "") -> list[dict[str, str]]:
    specs = [spec for spec in list_platforms() if _platform_tab_matches(spec, tab)]
    if kind != "Todos":
        specs = [spec for spec in specs if spec.kind == kind]
    if generation != "Todas":
        specs = [spec for spec in specs if spec.generation == generation]
    query = " ".join(query.casefold().split())
    if query:
        specs = [
            spec
            for spec in specs
            if query in " ".join([spec.name, spec.short_name, spec.brand, spec.kind, spec.generation, spec.dat_recommended, spec.extension_label]).casefold()
        ]
    return [
        {
            "id": spec.id.value,
            "icon": spec.icon,
            "icon_url": spec.icon_url or "",
            "name": spec.short_name,
            "brand": spec.brand,
            "generation": spec.generation,
            "kind": spec.kind,
            "extensions": spec.extension_label,
            "dat": spec.dat_recommended,
            "romset": spec.romset_recommended,
            "tip": spec.collection_tip,
            "ra": spec.ra_label,
            "complexity": spec.complexity,
            "notes": spec.notes,
        }
        for spec in specs
    ]


def _diagnostic_rows(rows) -> list[dict[str, str]]:
    return [
        {
            "status": row.status,
            "item": row.item,
            "detail": row.detail,
            "recommendation": row.recommendation,
        }
        for row in rows
    ]


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


def _ra_status_label(platform: Platform) -> str:
    status = ra_sync_status(platform)
    hashes = ra_cache_count(platform)
    games = int(status.get("cached_games", 0) or 0)
    detailed = int(status.get("detailed_games", 0) or 0)
    remaining = int(status.get("remaining_details", 0) or 0)
    hashes_at = status.get("hashes_at", "nunca")
    details_at = status.get("details_at", "nunca")
    return (
        f"Hashes RA: {hashes} hashes / {games} juegos. "
        f"Detalles: {detailed} juegos, pendientes {remaining}. "
        f"Últimos syncs: hashes {hashes_at}; detalles {details_at}."
    )
