"""Verificación de una colección contra un DAT, sin generar plan ni tocar archivos."""
from __future__ import annotations

import csv
import html
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


VERIFY_METRIC_LABELS = [
    ("dat_games", "Juegos en el DAT"),
    ("romset_games", "Juegos en el romset"),
    ("matched_games", "Coincidentes"),
    ("missing", "Faltantes"),
    ("unmatched", "Fuera del DAT"),
    ("misnamed", "Mal nombrados"),
    ("duplicates", "Duplicados"),
]

_STATUS_COLORS = {"FALTA": "#c62828", "SIN DAT": "#8a5a44", "MAL NOMBRADO": "#b8860b", "DUPLICADO": "#276a73"}


def report_verify(report: VerifyReport, path: Path, fmt: str) -> Path:
    """Escribe el informe de verificación en json, csv o html."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    elif fmt == "csv":
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["metrica", "valor"])
            for key, label in VERIFY_METRIC_LABELS:
                writer.writerow([label, getattr(report, key)])
            writer.writerow([])
            writer.writerow(["estado", "juego", "detalle"])
            for issue in report.issues:
                writer.writerow([issue.status, issue.title, issue.detail])
    elif fmt == "html":
        metrics = "".join(
            f"<div class='metric'><strong>{getattr(report, key)}</strong><span>{html.escape(label)}</span></div>"
            for key, label in VERIFY_METRIC_LABELS
        )
        if report.clean:
            body = "<p class='clean'>Colección verificada: sin incidencias respecto al DAT. ✔</p>"
        else:
            rows = "\n".join(
                "<tr>"
                f"<td><span class='pill' style='background:{_STATUS_COLORS.get(issue.status, '#56636a')}'>{html.escape(issue.status)}</span></td>"
                f"<td>{html.escape(issue.title)}</td>"
                f"<td>{html.escape(issue.detail)}</td>"
                "</tr>"
                for issue in report.issues
            )
            body = f"<table><thead><tr><th>Estado</th><th>Juego</th><th>Detalle</th></tr></thead><tbody>{rows}</tbody></table>"
        path.write_text(
            f"""<!doctype html>
<html><head><meta charset="utf-8"><title>RetroPerfect · Verificación</title>
<style>
body{{font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,sans-serif;margin:0;background:#f6f7f8;color:#172326}}
header{{background:#276a73;color:white;padding:2rem 2.5rem}}
main{{padding:2rem 2.5rem}}
h1{{margin:.2rem 0;font-size:2rem}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.8rem;margin:1.5rem 0}}
.metric{{background:white;border:1px solid #d8e1e4;border-radius:8px;padding:1rem}}
.metric strong{{display:block;font-size:1.6rem;color:#276a73}} .metric span{{color:#56636a}}
table{{border-collapse:collapse;width:100%;background:white;border:1px solid #d8e1e4;border-radius:8px;overflow:hidden}}
td,th{{border-bottom:1px solid #e4eaec;padding:.55rem;vertical-align:top;font-size:.9rem;text-align:left}}th{{background:#eef7f8}}
.pill{{color:white;border-radius:999px;padding:.15rem .55rem;font-weight:600;font-size:.8rem;white-space:nowrap}}
.clean{{background:#e6f4ea;color:#137333;border-radius:8px;padding:1rem;font-weight:600}}
</style></head>
<body><header><h1>Verificación de colección</h1></header>
<main><div class="metrics">{metrics}</div>{body}</main></body></html>""",
            encoding="utf-8",
        )
    else:
        raise ValueError(f"Formato de informe no soportado: {fmt}")
    return path
