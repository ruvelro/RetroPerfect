from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel

from .metadata import parse_no_intro_name
from .models import DatCatalog, Manifest, ScanResult


class CoverageRow(BaseModel):
    group_key: str
    title: str
    in_dat: bool
    in_romset: bool
    matched: bool
    will_keep_main: bool
    will_keep_ra: bool
    will_drop_all: bool
    dat_variants: int = 0
    rom_variants: int = 0
    matched_variants: int = 0
    ra_variants: int = 0
    dat_regions: list[str] = []
    rom_regions: list[str] = []
    kept_paths: list[str] = []
    missing_reason: str = ""


class CoverageSummary(BaseModel):
    dat_games: int
    romset_games: int
    matched_games: int
    missing_from_romset: int
    unmatched_romset_games: int
    hash_mismatch_games: int = 0
    will_keep_games: int
    will_drop_all_games: int
    rows: list[CoverageRow]


def build_coverage(scan: ScanResult, catalog: DatCatalog | None = None, manifest: Manifest | None = None) -> CoverageSummary:
    dat_groups: dict[str, list] = defaultdict(list)
    if catalog:
        for game in catalog.games:
            dat_groups[_dat_coverage_key(game)].append(game)

    rom_groups = defaultdict(list)
    for rom in scan.roms:
        rom_groups[_rom_coverage_key(rom)].append(rom)

    kept_by_group: dict[str, list[str]] = defaultdict(list)
    keep_buckets: dict[str, set[str]] = defaultdict(set)
    if manifest:
        rom_by_id = {rom.id: rom for rom in scan.roms}
        for entry in manifest.entries:
            kept_rom = rom_by_id.get(entry.rom_id)
            if kept_rom:
                group_key = _rom_coverage_key(kept_rom)
                kept_by_group[group_key].append(entry.source_path)
                keep_buckets[group_key].add(entry.bucket.value)

    keys = sorted(set(dat_groups) | set(rom_groups), key=str.lower)
    rows: list[CoverageRow] = []
    for key in keys:
        dat_games = dat_groups.get(key, [])
        roms = rom_groups.get(key, [])
        dat_regions = sorted({region for game in dat_games for region in game.releases})
        rom_regions = sorted({region for rom in roms for region in rom.metadata.regions})
        matched_variants = sum(1 for rom in roms if rom.dat_game is not None)
        title = _display_title(key, dat_games, roms)
        in_dat = bool(dat_games)
        in_romset = bool(roms)
        matched = matched_variants > 0
        will_keep_main = "main" in keep_buckets.get(key, set())
        will_keep_ra = "ra" in keep_buckets.get(key, set())
        will_keep = will_keep_main or will_keep_ra
        missing_reason = ""
        if in_dat and not in_romset:
            missing_reason = "Está en el DAT, pero no aparece ninguna variante en tu romset."
        elif in_romset and not matched:
            missing_reason = "Está en tu romset, pero no coincide con el DAT cargado."
        elif in_romset and manifest and not will_keep:
            missing_reason = "Hay variantes, pero ninguna pasa el perfil actual."

        rows.append(
            CoverageRow(
                group_key=key,
                title=title,
                in_dat=in_dat,
                in_romset=in_romset,
                matched=matched,
                will_keep_main=will_keep_main,
                will_keep_ra=will_keep_ra,
                will_drop_all=in_romset and manifest is not None and not will_keep,
                dat_variants=sum(len(game.roms) for game in dat_games),
                rom_variants=len(roms),
                matched_variants=matched_variants,
                ra_variants=sum(1 for rom in roms if rom.ra_game_id is not None),
                dat_regions=dat_regions,
                rom_regions=rom_regions,
                kept_paths=sorted(set(kept_by_group.get(key, []))),
                missing_reason=missing_reason,
            )
        )

    return CoverageSummary(
        dat_games=len(dat_groups),
        romset_games=len(rom_groups),
        matched_games=sum(1 for row in rows if row.matched),
        missing_from_romset=sum(1 for row in rows if row.in_dat and not row.in_romset),
        unmatched_romset_games=sum(1 for row in rows if row.in_romset and not row.in_dat),
        hash_mismatch_games=sum(1 for row in rows if row.in_dat and row.in_romset and not row.matched),
        will_keep_games=sum(1 for row in rows if row.will_keep_main or row.will_keep_ra),
        will_drop_all_games=sum(1 for row in rows if row.will_drop_all),
        rows=rows,
    )


def _display_title(key: str, dat_games: list, roms: list) -> str:
    if dat_games:
        return parse_no_intro_name(dat_games[0].description or dat_games[0].name).title
    if roms:
        return roms[0].metadata.title
    return Path(key).stem


def _dat_coverage_key(game) -> str:
    if game.cloneof:
        return game.group_key
    return parse_no_intro_name(game.description or game.name).title


def _rom_coverage_key(rom) -> str:
    if rom.dat_game and rom.dat_game.cloneof:
        return rom.dat_game.group_key
    return rom.metadata.title
