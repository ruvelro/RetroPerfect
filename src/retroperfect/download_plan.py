"""Plan de descarga: qué falta según el DAT y el perfil, y dónde está en las fuentes.

La gracia frente a un gestor de descargas genérico es no bajar el set entero:
se parte de los juegos del DAT que no aparecen en el escaneo, se aplica el mismo
perfil que decide el 1G1R (una variante por grupo parent/clone) y solo entonces
se busca cada candidato en el índice de la fuente.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .metadata import parse_no_intro_name
from .models import DatCatalog, DatGame, DetectedMetadata, OutputBucket, Platform, ProfileOutput, ScanResult, SelectionProfile
from .rom_sources import RemoteFile, RomSource, resolve_source
from .rules import STRICT_1G1R_TAGS, priority_index

# Cuánto fiarse del emparejamiento con el archivo remoto. La descarga se verifica
# siempre contra el DAT, así que esto solo ordena y avisa antes de bajar nada.
CONFIDENCE_LABELS = {
    "hash": "Hash del índice coincide con el DAT",
    "name-exact": "Nombre idéntico al del DAT",
    "name-fuzzy": "Mismo título, variante distinta o sin confirmar",
}

CONFIDENCE_ORDER = {"hash": 0, "name-exact": 1, "name-fuzzy": 2}


class DownloadCandidate(BaseModel):
    group_key: str
    game_name: str
    title: str
    source_id: str
    file_name: str
    url: str
    size: int | None = None
    confidence: str = "name-fuzzy"
    expected_crc32: str | None = None
    expected_md5: str | None = None
    expected_sha1: str | None = None
    regions: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @property
    def confidence_label(self) -> str:
        return CONFIDENCE_LABELS.get(self.confidence, self.confidence)


class MissingGame(BaseModel):
    group_key: str
    game_name: str
    title: str
    reason: str


class DownloadPlan(BaseModel):
    platform: Platform
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    candidates: list[DownloadCandidate] = Field(default_factory=list)
    unavailable: list[MissingGame] = Field(default_factory=list)
    dat_groups: int = 0
    present_groups: int = 0
    filtered_by_profile: int = 0

    @property
    def total_bytes(self) -> int:
        return sum(candidate.size or 0 for candidate in self.candidates)

    @property
    def unknown_size_count(self) -> int:
        return sum(1 for candidate in self.candidates if candidate.size is None)


def build_download_plan(
    catalog: DatCatalog,
    scan: ScanResult | None,
    profile: SelectionProfile,
    remote_files: dict[str, list[RemoteFile]],
    *,
    platform: Platform,
    apply_profile: bool = True,
) -> DownloadPlan:
    """Cruza los juegos ausentes del DAT con los índices remotos, ya filtrados por perfil."""
    groups: dict[str, list[DatGame]] = {}
    for game in catalog.games:
        groups.setdefault(group_key(game), []).append(game)

    present = _present_groups(scan)
    output = _main_output(profile)
    plan = DownloadPlan(platform=platform, dat_groups=len(groups), present_groups=len(present & set(groups)))
    lookup = _RemoteLookup(remote_files)

    for key, games in sorted(groups.items(), key=lambda item: item[0].lower()):
        if key in present:
            continue
        wanted = _select_variants(games, output, apply_profile)
        if not wanted:
            plan.filtered_by_profile += 1
            continue
        matches = [match for game in wanted if (match := lookup.find(game))]
        if not matches:
            best = wanted[0]
            plan.unavailable.append(
                MissingGame(
                    group_key=key,
                    game_name=best.name,
                    title=_title(best),
                    reason="Ninguna fuente configurada ofrece este juego.",
                )
            )
            continue
        game, source_id, remote, confidence = min(matches, key=lambda item: CONFIDENCE_ORDER.get(item[3], 9))
        plan.candidates.append(_candidate(key, game, source_id, remote, confidence))

    plan.candidates.sort(key=lambda item: item.title.lower())
    return plan


def resolve_remote_files(sources: list[RomSource], refresh: bool = False) -> tuple[dict[str, list[RemoteFile]], list[str]]:
    """Resuelve varias fuentes y devuelve (archivos por fuente, errores legibles)."""
    files: dict[str, list[RemoteFile]] = {}
    errors: list[str] = []
    for source in sources:
        if not source.enabled:
            continue
        try:
            files[source.id] = resolve_source(source, refresh=refresh).files
        except Exception as exc:
            errors.append(f"{source.label}: {exc}")
    return files, errors


class _RemoteLookup:
    """Índice de los archivos remotos por hash y por nombre normalizado."""

    def __init__(self, remote_files: dict[str, list[RemoteFile]]) -> None:
        self.by_hash: dict[str, tuple[str, RemoteFile]] = {}
        self.by_name: dict[str, list[tuple[str, RemoteFile]]] = {}
        self.by_title: dict[str, list[tuple[str, RemoteFile]]] = {}
        for source_id, files in remote_files.items():
            for remote in files:
                for value in [_hash_key(remote.md5), _hash_key(remote.sha1), _crc_key(remote.crc32)]:
                    if value:
                        self.by_hash.setdefault(value, (source_id, remote))
                self.by_name.setdefault(_name_key(remote.name), []).append((source_id, remote))
                self.by_title.setdefault(_title_key(remote.name), []).append((source_id, remote))

    def find(self, game: DatGame) -> tuple[DatGame, str, RemoteFile, str] | None:
        for rom in game.roms:
            for value in [_hash_key(rom.md5), _hash_key(rom.sha1), _crc_key(rom.crc32)]:
                hit = self.by_hash.get(value) if value else None
                if hit:
                    return game, hit[0], hit[1], "hash"

        names = [rom.name for rom in game.roms] + [game.name, game.description or ""]
        for name in filter(None, names):
            exact = self.by_name.get(_name_key(name))
            if exact:
                return game, exact[0][0], exact[0][1], "name-exact"

        metadata = _metadata(game)
        for name in filter(None, names):
            fuzzy = self.by_title.get(_title_key(name))
            if not fuzzy:
                continue
            same_region = [item for item in fuzzy if _regions_overlap(metadata, item[1].name)]
            chosen = (same_region or fuzzy)[0]
            return game, chosen[0], chosen[1], "name-fuzzy"
        return None


def _candidate(key: str, game: DatGame, source_id: str, remote: RemoteFile, confidence: str) -> DownloadCandidate:
    metadata = _metadata(game)
    rom = game.roms[0] if game.roms else None
    return DownloadCandidate(
        group_key=key,
        game_name=game.name,
        title=metadata.title,
        source_id=source_id,
        file_name=remote.name,
        url=remote.url,
        size=remote.size or (rom.size if rom else None),
        confidence=confidence,
        expected_crc32=rom.crc32 if rom else None,
        expected_md5=rom.md5 if rom else None,
        expected_sha1=rom.sha1 if rom else None,
        regions=metadata.regions,
        languages=metadata.languages,
        tags=metadata.tags,
    )


def group_key(game: DatGame) -> str:
    """Título del grupo 1G1R al que pertenece el juego.

    Se resuelve por el parent cuando el DAT trae parent/clone (así entran juntas las
    variantes retituladas, tipo Probotector/Contra) y por el propio título cuando no:
    los DAT sin esas relaciones dejarían cada región como juego suelto y el filtro
    1G1R no descartaría nada.
    """
    return parse_no_intro_name(game.cloneof or game.description or game.name).title


def _present_groups(scan: ScanResult | None) -> set[str]:
    if scan is None:
        return set()
    return {group_key(rom.dat_game) for rom in scan.roms if rom.dat_game}


def _main_output(profile: SelectionProfile) -> ProfileOutput:
    for output in profile.outputs:
        if output.bucket == OutputBucket.MAIN:
            return output
    return profile.outputs[0] if profile.outputs else ProfileOutput(bucket=OutputBucket.MAIN)


def _select_variants(games: list[DatGame], output: ProfileOutput, apply_profile: bool) -> list[DatGame]:
    """Sin perfil, todas las variantes del grupo; con perfil, solo la que ganaría el 1G1R."""
    if not apply_profile:
        return games
    allowed = [game for game in games if _allowed(game, output)]
    if not allowed:
        return []
    return [min(allowed, key=lambda game: _score(game, output))]


def _allowed(game: DatGame, output: ProfileOutput) -> bool:
    metadata = _metadata(game)
    tags = set(metadata.tags)
    if output.strict_1g1r and tags & STRICT_1G1R_TAGS:
        return False
    return not tags & set(output.tag_excludes)


def _score(game: DatGame, output: ProfileOutput) -> tuple:
    metadata = _metadata(game)
    return (
        priority_index(metadata.regions, output.region_priority),
        priority_index(metadata.languages, output.language_priority),
        -metadata.revision if output.prefer_newest_revision else metadata.revision,
        game.name.lower(),
    )


def _metadata(game: DatGame) -> DetectedMetadata:
    return parse_no_intro_name(game.description or game.name)


def _title(game: DatGame) -> str:
    return _metadata(game).title


def _regions_overlap(metadata: DetectedMetadata, remote_name: str) -> bool:
    remote_regions = set(parse_no_intro_name(remote_name).regions)
    if not remote_regions or not metadata.regions:
        return False
    return bool(remote_regions & set(metadata.regions))


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", Path(name).stem.casefold())


def _title_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", parse_no_intro_name(name).title.casefold())


def human_size(size: int | None) -> str:
    if not size:
        return "?"
    value = float(size)
    for unit in ["B", "KiB", "MiB", "GiB"]:
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def _hash_key(value: str | None) -> str | None:
    return value.strip().lower() if value else None


def _crc_key(value: str | None) -> str | None:
    """El CRC32 se compara con relleno a 8 dígitos: archive.org lo publica sin ceros a la izquierda."""
    cleaned = _hash_key(value)
    return f"crc:{cleaned.zfill(8)}" if cleaned else None
