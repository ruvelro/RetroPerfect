"""Filas de cobertura del romset frente al DAT."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .decisions import (
    _decision_detail,
    _discard_reasons_by_rom,
    _discard_reasons_for_group,
    _entry_reasons_by_rom,
    _entry_reasons_for_group,
    _output_detail,
    _output_label,
    _rom_summary_key,
    _variant_status,
    _variant_visual,
)
from .styles import _flag_regions, _ra_icon


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
