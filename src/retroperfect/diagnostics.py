from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import zipfile
from urllib.parse import urlparse

from pydantic import BaseModel

from .coverage import CoverageSummary
from .dat_manager import DatMetadata, inspect_dat, list_installed_dats
from .models import DatCatalog, Manifest, Platform, ScanResult
from .platforms import platform_spec


class AuditSummary(BaseModel):
    score: int
    verdict: str
    complete_games: int
    missing_games: int
    unmatched_games: int
    duplicate_groups: int
    ra_covered_games: int
    ra_missing_games: int
    patch_pending: int
    notes: list[str]


class DiagnosticRow(BaseModel):
    status: str
    item: str
    detail: str
    recommendation: str = ""


class PatchQueueRow(BaseModel):
    status: str
    game: str
    source: str
    patch: str
    expected_md5: str
    destination: str


def build_perfect_audit(summary: CoverageSummary | None, scan: ScanResult | None, manifest: Manifest | None) -> AuditSummary:
    if summary is None or scan is None:
        return AuditSummary(
            score=0,
            verdict="Pendiente de escaneo",
            complete_games=0,
            missing_games=0,
            unmatched_games=0,
            duplicate_groups=0,
            ra_covered_games=0,
            ra_missing_games=0,
            patch_pending=0,
            notes=["Escanea con DAT y crea un plan para calcular la auditoría final."],
        )
    rom_groups: dict[str, list] = defaultdict(list)
    for rom in scan.roms:
        rom_groups[rom.group_key].append(rom)
    duplicate_groups = sum(1 for roms in rom_groups.values() if len({rom.container_path for rom in roms}) > 1)
    ra_rows = [row for row in summary.rows if row.in_romset]
    ra_covered = sum(1 for row in ra_rows if row.will_keep_ra or row.ra_variants > 0)
    ra_missing = sum(1 for row in ra_rows if row.ra_variants == 0 and not row.will_keep_ra)
    patch_pending = sum(1 for entry in (manifest.entries if manifest else []) if entry.patch_url)
    penalties = summary.missing_from_romset + summary.unmatched_romset_games + summary.hash_mismatch_games + summary.will_drop_all_games + duplicate_groups + ra_missing
    total = max(summary.dat_games + summary.romset_games, 1)
    score = max(0, min(100, round(100 - (penalties / total) * 100)))
    notes: list[str] = []
    if summary.missing_from_romset:
        notes.append(f"Faltan {summary.missing_from_romset} juegos presentes en el DAT.")
    if summary.unmatched_romset_games:
        notes.append(f"Hay {summary.unmatched_romset_games} juegos del romset fuera del DAT.")
    if duplicate_groups:
        notes.append(f"Hay {duplicate_groups} grupos con duplicados reales antes de aplicar 1G1R.")
    if ra_missing:
        notes.append(f"{ra_missing} juegos escaneados no tienen variante RA localizada.")
    if patch_pending:
        notes.append(f"{patch_pending} entradas RA se generarían aplicando parche.")
    if not notes:
        notes.append("Colección limpia según DAT, perfil y RA cacheado.")
    verdict = "Colección perfecta" if score >= 98 else ("Muy cerca" if score >= 85 else "Necesita revisión")
    return AuditSummary(
        score=score,
        verdict=verdict,
        complete_games=summary.matched_games,
        missing_games=summary.missing_from_romset,
        unmatched_games=summary.unmatched_romset_games,
        duplicate_groups=duplicate_groups,
        ra_covered_games=ra_covered,
        ra_missing_games=ra_missing,
        patch_pending=patch_pending,
        notes=notes,
    )


def detect_dat_warnings(platform: Platform, source: Path | None, dat: Path | None, scan: ScanResult | None = None) -> list[DiagnosticRow]:
    rows: list[DiagnosticRow] = []
    spec = platform_spec(platform)
    if dat is None:
        return [DiagnosticRow(status="MISS", item="DAT", detail="No hay DAT seleccionado.", recommendation=spec.dat_recommended)]
    try:
        metadata = inspect_dat(dat, platform=platform)
    except Exception as exc:
        return [DiagnosticRow(status="MISS", item="DAT", detail=f"No se pudo leer el DAT: {exc}", recommendation="Importa un DAT válido .dat/.xml/.zip.")]

    dat_text = " ".join([metadata.name, metadata.description or "", Path(metadata.path).name]).lower()
    source_text = str(source or "").lower()
    if metadata.platform not in {None, platform.value}:
        rows.append(DiagnosticRow(status="WARN", item="Plataforma DAT", detail=f"El DAT parece {metadata.platform}, pero la plataforma activa es {platform.value}.", recommendation="Usa un DAT de la misma plataforma."))
    if not metadata.parent_clone:
        rows.append(DiagnosticRow(status="WARN", item="Parent/Clone", detail="El DAT no parece Parent/Clone.", recommendation="Para 1G1R fiable, descarga Parent/Clone XML si existe."))
    if spec.kind == "arcade":
        rows.extend(_arcade_warnings(metadata, source, scan))
    if platform == Platform.NES:
        rom_headered, rom_unheadered = _nes_header_counts(scan)
        if metadata.header_mode == "headered" and rom_unheadered and not rom_headered:
            rows.append(DiagnosticRow(status="WARN", item="NES header", detail="DAT headered con romset aparentemente unheadered.", recommendation="Usa DAT unheadered o romset headered/iNES."))
        if metadata.header_mode == "unheadered" and rom_headered:
            rows.append(DiagnosticRow(status="WARN", item="NES header", detail="DAT unheadered con ROMs iNES/headered.", recommendation="RetroPerfect intenta emparejar, pero para emulación se recomienda DAT/romset headered."))
    if platform == Platform.N64:
        dat_mode = _n64_dat_mode(dat_text)
        rom_mode = _n64_rom_mode(scan)
        if dat_mode and rom_mode and dat_mode != rom_mode:
            rows.append(DiagnosticRow(status="WARN", item="N64 endian", detail=f"DAT {dat_mode} con romset {rom_mode}.", recommendation="Preferible DAT BigEndian con .z64; se intenta normalizar .n64/.v64."))
        if not dat_mode:
            rows.append(DiagnosticRow(status="INFO", item="N64 DAT", detail="No se detecta variante BigEndian/ByteSwapped en el nombre del DAT.", recommendation="Para No-Intro usa BigEndian salvo que tu romset indique otra cosa."))
    if platform == Platform.A7800:
        uses_a78 = bool(scan and any(Path(rom.container_path).suffix.lower() == ".a78" for rom in scan.roms))
        uses_bin = bool(scan and any(Path(rom.container_path).suffix.lower() == ".bin" for rom in scan.roms))
        if "a78" in dat_text and uses_bin and not uses_a78:
            rows.append(DiagnosticRow(status="WARN", item="Atari 7800", detail="DAT A78 con romset BIN.", recommendation="Usa DAT BIN o romset A78."))
        if "bin" in dat_text and uses_a78:
            rows.append(DiagnosticRow(status="WARN", item="Atari 7800", detail="DAT BIN con romset A78.", recommendation="Usa DAT A78 o romset BIN."))
    if platform == Platform.SNES and scan:
        smc_count = sum(1 for rom in scan.roms if Path(rom.container_path).suffix.lower() == ".smc")
        if smc_count:
            rows.append(DiagnosticRow(status="INFO", item="SNES header", detail=f"{smc_count} archivos .smc detectados.", recommendation="Si llevan copier header, RetroPerfect intenta normalizar; SFC/headerless es más limpio."))
    if not rows:
        rows.append(DiagnosticRow(status="OK", item="DAT", detail="No se detectan incompatibilidades obvias.", recommendation=spec.dat_recommended))
    return rows


def _arcade_warnings(metadata: DatMetadata, source: Path | None, scan: ScanResult | None) -> list[DiagnosticRow]:
    rows = [
        DiagnosticRow(
            status="INFO",
            item="Arcade",
            detail="Arcade usa sets con parents, clones, BIOS, devices y a veces CHD.",
            recommendation="Mantén DAT, romset y core/emulador en la misma version antes de filtrar.",
        )
    ]
    dat_text = " ".join([metadata.name, metadata.description or "", Path(metadata.path).name]).lower()
    source_text = str(source or "").lower()
    if not any(token in dat_text for token in ["mame", "fbneo", "finalburn", "hbmame", "arcade"]):
        rows.append(DiagnosticRow(status="WARN", item="Arcade DAT", detail="El DAT no parece indicar MAME/FBNeo/arcade.", recommendation="Comprueba que no has cargado un DAT No-Intro de consola por error."))
    if scan:
        chd_count = sum(1 for rom in scan.roms if Path(rom.container_path).suffix.lower() == ".chd")
        zip_count = sum(1 for rom in scan.roms if Path(rom.container_path).suffix.lower() in {".zip", ".7z"})
        clone_count = sum(1 for rom in scan.roms if rom.dat_game and rom.dat_game.cloneof)
        if chd_count:
            rows.append(DiagnosticRow(status="WARN", item="CHD", detail=f"{chd_count} CHD detectados.", recommendation="Verifica que su ZIP parent tambien se conserva; un CHD suelto no suele bastar."))
        if clone_count:
            rows.append(DiagnosticRow(status="INFO", item="Clones", detail=f"{clone_count} sets con parent/clone detectados.", recommendation="En arcade los clones pueden ser regiones, bootlegs, revisions o variantes jugables; revisa el perfil antes de borrar."))
        if zip_count and "non-merged" not in source_text and "nonmerged" not in source_text:
            rows.append(DiagnosticRow(status="INFO", item="Split/merged", detail="No se detecta si el origen es split, merged o non-merged.", recommendation="Para colecciones selectivas, non-merged evita dependencias ocultas; split/merged requiere conservar parents/BIOS."))
    return rows


def build_patch_queue(manifest: Manifest | None) -> list[PatchQueueRow]:
    if manifest is None:
        return []
    rows: list[PatchQueueRow] = []
    for entry in manifest.entries:
        if not entry.patch_url:
            continue
        suffix = Path(urlparse(entry.patch_url).path).suffix.lower()
        if suffix in {".ips", ".bps", ".zip"}:
            status = "Listo"
        elif suffix:
            status = f"Pendiente ({suffix})"
        else:
            status = "Pendiente"
        rows.append(
            PatchQueueRow(
                status=status,
                game=entry.patch_name or entry.dat_name or entry.rom_id,
                source=Path(entry.source_path).name,
                patch=entry.patch_url,
                expected_md5=entry.patch_expected_md5 or "",
                destination=entry.destination_path or "",
            )
        )
    return rows


def build_needed_rows(platform: Platform, source: Path | None, dat: Path | None, scan: ScanResult | None = None) -> list[DiagnosticRow]:
    spec = platform_spec(platform)
    installed = [item for item in list_installed_dats() if item.platform in {None, platform.value}]
    rows = [
        DiagnosticRow(status="INFO", item="DAT recomendado", detail=spec.dat_recommended, recommendation="Biblioteca DAT puede descargar espejo Libretro o abrir DAT-o-MATIC oficial."),
        DiagnosticRow(status="INFO", item="Romset recomendado", detail=spec.romset_recommended, recommendation=spec.collection_tip),
        DiagnosticRow(status="OK" if installed else "MISS", item="DAT instalado", detail=f"{len(installed)} DAT(s) compatibles instalados." if installed else "No hay DAT compatible instalado.", recommendation="Importa/descarga un DAT antes de escanear."),
        DiagnosticRow(status="OK" if source and source.exists() else "MISS", item="Romset/origen", detail=str(source) if source else "No seleccionado.", recommendation=f"Extensiones esperadas: {spec.extension_label}, .zip"),
    ]
    rows.extend(detect_dat_warnings(platform, source, dat, scan))
    rows.extend(preflight_source_warnings(platform, source, dat))
    return rows


def preflight_source_warnings(platform: Platform, source: Path | None, dat: Path | None = None) -> list[DiagnosticRow]:
    if source is None or not source.exists():
        return []
    spec = platform_spec(platform)
    paths = [source] if source.is_file() else [path for path in source.rglob("*") if path.is_file()]
    sample = paths[:500]
    suffix_counts = Counter(path.suffix.lower() for path in sample)
    rows: list[DiagnosticRow] = []
    expected = set(spec.extensions)
    unexpected = {suffix: count for suffix, count in suffix_counts.items() if suffix and suffix not in expected}
    if unexpected and len(unexpected) >= max(1, len(suffix_counts) // 2):
        detail = ", ".join(f"{suffix}: {count}" for suffix, count in sorted(unexpected.items())[:6])
        rows.append(DiagnosticRow(status="WARN", item="Origen", detail=f"Muchas extensiones no parecen de {spec.short_name}: {detail}", recommendation=f"Comprueba la plataforma o usa un origen con {spec.extension_label}."))
    if platform == Platform.N64:
        if suffix_counts.get(".v64") and dat and "bigendian" in dat.name.lower():
            rows.append(DiagnosticRow(status="WARN", item="Preflight N64", detail="El origen parece ByteSwapped (.v64) y el DAT BigEndian.", recommendation="Se intentará normalizar, pero lo más claro es usar romset .z64 BigEndian."))
    if platform == Platform.A7800:
        if suffix_counts.get(".bin") and dat and "a78" in dat.name.lower():
            rows.append(DiagnosticRow(status="WARN", item="Preflight A7800", detail="El origen tiene BIN y el DAT parece A78.", recommendation="Mejor usar DAT/romset de la misma variante."))
    if spec.kind == "arcade":
        zip_count = suffix_counts.get(".zip", 0) + suffix_counts.get(".7z", 0)
        chd_count = suffix_counts.get(".chd", 0)
        if chd_count and not zip_count:
            rows.append(DiagnosticRow(status="WARN", item="Preflight arcade", detail="Hay CHDs pero no se ven ZIP/7Z de sets en la muestra.", recommendation="Los CHD suelen necesitar su set parent y BIOS del mismo DAT."))
        if zip_count and any(_zip_has_many_inner_roms(path) for path in sample if path.suffix.lower() == ".zip"):
            rows.append(DiagnosticRow(status="INFO", item="Preflight arcade", detail="Los ZIP arcade se tratarán como sets completos por nombre.", recommendation="No se escogerán ROMs internas como si fueran juegos independientes."))
    return rows


def _zip_has_many_inner_roms(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return sum(1 for info in archive.infolist() if not info.is_dir()) > 3
    except (OSError, zipfile.BadZipFile):
        return False


def _nes_header_counts(scan: ScanResult | None) -> tuple[int, int]:
    if scan is None:
        return 0, 0
    headered = sum(1 for rom in scan.roms if rom.hashes.size != (rom.hashes.payload_size or rom.hashes.size))
    unheadered = max(0, len(scan.roms) - headered)
    return headered, unheadered


def _n64_dat_mode(text: str) -> str | None:
    if "bigendian" in text or "big endian" in text:
        return "BigEndian"
    if "byteswapped" in text or "byte swapped" in text:
        return "ByteSwapped"
    if "littleendian" in text or "little endian" in text:
        return "LittleEndian"
    return None


def _n64_rom_mode(scan: ScanResult | None) -> str | None:
    if scan is None:
        return None
    modes = Counter()
    for rom in scan.roms:
        suffix = Path(rom.container_path).suffix.lower()
        if suffix == ".z64":
            modes["BigEndian"] += 1
        elif suffix == ".v64":
            modes["ByteSwapped"] += 1
        elif suffix == ".n64":
            modes["LittleEndian"] += 1
    return modes.most_common(1)[0][0] if modes else None
