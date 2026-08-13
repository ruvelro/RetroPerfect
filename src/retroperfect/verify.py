"""Verificación de una colección contra un DAT, sin generar plan ni tocar archivos."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel

from .coverage import build_coverage
from .models import DatCatalog, ScannedRom, ScanResult


class VerifyIssue(BaseModel):
    status: str
    title: str
    detail: str


class VerifyReport(BaseModel):
    dat_games: int
    romset_games: int
    matched_games: int
    missing: int
    unmatched: int
    misnamed: int
    duplicates: int
    issues: list[VerifyIssue]

    @property
    def clean(self) -> bool:
        return not self.issues


def _rom_file_name(rom: ScannedRom) -> str:
    if rom.inner_path:
        return Path(rom.inner_path).name
    return Path(rom.container_path).name


def _expected_name(rom: ScannedRom) -> str | None:
    if rom.dat_game and rom.dat_game.roms:
        return Path(rom.dat_game.roms[0].name).name
    return None


def verify_collection(scan: ScanResult, catalog: DatCatalog) -> VerifyReport:
    summary = build_coverage(scan, catalog)
    issues: list[VerifyIssue] = []

    missing = 0
    unmatched = 0
    for row in summary.rows:
        if row.in_dat and not row.in_romset:
            missing += 1
            regions = f" ({', '.join(row.dat_regions)})" if row.dat_regions else ""
            issues.append(VerifyIssue(status="FALTA", title=row.title, detail=f"En el DAT pero sin ninguna variante en el romset{regions}."))
        elif row.in_romset and not row.matched:
            unmatched += 1
            files = sorted({_rom_file_name(rom) for rom in scan.roms if rom.metadata.title == row.title and rom.dat_game is None})
            issues.append(VerifyIssue(status="SIN DAT", title=row.title, detail="No coincide con el DAT: " + ", ".join(files[:4])))

    misnamed = 0
    for rom in scan.roms:
        expected = _expected_name(rom)
        if expected is None:
            continue
        actual = _rom_file_name(rom)
        if Path(actual).stem.casefold() != Path(expected).stem.casefold():
            misnamed += 1
            issues.append(VerifyIssue(status="MAL NOMBRADO", title=rom.metadata.title, detail=f"{actual} debería llamarse {expected}"))

    duplicates = 0
    by_md5: dict[str, set[str]] = defaultdict(set)
    for rom in scan.roms:
        by_md5[rom.hashes.md5].add(rom.container_path)
    for md5, containers in sorted(by_md5.items()):
        if len(containers) > 1:
            duplicates += 1
            names = sorted(Path(container).name for container in containers)
            issues.append(VerifyIssue(status="DUPLICADO", title=names[0], detail=f"MD5 {md5[:12]} repetido en: " + ", ".join(names[:4])))

    return VerifyReport(
        dat_games=summary.dat_games,
        romset_games=summary.romset_games,
        matched_games=summary.matched_games,
        missing=missing,
        unmatched=unmatched,
        misnamed=misnamed,
        duplicates=duplicates,
        issues=issues,
    )
