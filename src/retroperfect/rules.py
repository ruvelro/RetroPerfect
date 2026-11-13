from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .metadata import parse_no_intro_name, strip_part, with_part
from .models import (
    ARCHIVE_MODES,
    ActionMode,
    CandidateDecision,
    ContainerMode,
    ExportLayout,
    Manifest,
    ManifestArchive,
    ManifestArchiveMember,
    ManifestEntry,
    ManifestPlaylist,
    OutputBucket,
    ProfileOutput,
    ScannedRom,
    ScanResult,
    SelectionProfile,
)
from .platforms import platform_spec
from .ra import RaPatchCandidate, normalize_ra_title, ra_patch_index

# Fragmentos de los motivos que la interfaz reconoce para elegir el icono de
# cada decisión. Viven aquí, junto a quien los escribe, porque la GUI los
# buscaba como subcadenas copiadas a mano en su propio módulo: traducir un
# motivo dejaba la pestaña Decisiones sin su icono y ningún test lo veía.
MOTIVO_OVERRIDE = "elegido a mano"
MOTIVO_1G1R = "1G1R estricto"
MOTIVO_SIN_RA = "sin hash compatible con RetroAchievements"
MOTIVO_RA = "RetroAchievements"
MOTIVO_PARCHE = "parche"
MOTIVO_TAG_EXCLUIDO = "excluido por etiqueta"
MOTIVO_SIN_DAT = "sin coincidencia en el DAT"
MOTIVO_REGION = "región"
MOTIVO_IDIOMA = "idioma"
MOTIVO_REVISION = "revisión"
MOTIVO_DAT_OK = "verificado contra el DAT"
MOTIVO_DAT_COINCIDE = "coincide con el DAT"


def _en_mayuscula(motivo: str) -> str:
    """Pone en mayúscula solo la primera letra.

    `str.capitalize()` pasa el resto a minúsculas y dejaba "Coincide con el dat"
    y "compatible con retroachievements".
    """
    return motivo[:1].upper() + motivo[1:]


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


def priority_index(values: list[str], priority: list[str]) -> int:
    if not values:
        return len(priority) + 10
    indexes = [priority.index(value) for value in values if value in priority]
    return min(indexes) if indexes else len(priority) + 5


def explain_score(rom: ScannedRom, output: ProfileOutput) -> list[str]:
    region_rank = priority_index(rom.metadata.regions, output.region_priority)
    language_rank = priority_index(rom.metadata.languages, output.language_priority)
    revision_label = rom.metadata.version or (str(rom.metadata.revision) if rom.metadata.revision else "unknown")
    reasons = [
        f"Prioridad de {MOTIVO_REGION} {region_rank}: {', '.join(rom.metadata.regions) or 'desconocida'}",
        f"Prioridad de {MOTIVO_IDIOMA} {language_rank}: {', '.join(rom.metadata.languages) or 'desconocido'}",
        f"{_en_mayuscula(MOTIVO_REVISION)}: {revision_label}",
        _en_mayuscula(MOTIVO_DAT_OK) if rom.dat_game else _en_mayuscula(MOTIVO_SIN_DAT),
    ]
    if rom.ra_game_id:
        reasons.append(f"Compatible con {MOTIVO_RA}: {rom.ra_title or rom.ra_game_id}")
    if output.prefer_ra_compatible and not output.require_ra:
        reasons.append(f"Las variantes compatibles con {MOTIVO_RA} pueden servir para el 1G1R principal")
    return reasons


def _allowed(rom: ScannedRom, output: ProfileOutput) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if output.strict_1g1r and not rom.dat_game:
        return False, [f"Excluido por {MOTIVO_1G1R}: {MOTIVO_SIN_DAT}"]
    strict_excluded = _strict_exclusions(rom) if output.strict_1g1r else []
    if strict_excluded:
        return False, [f"Excluido por {MOTIVO_1G1R}, etiqueta: {', '.join(strict_excluded)}"]
    if output.require_ra and not rom.ra_game_id:
        return False, [_en_mayuscula(MOTIVO_SIN_RA)]
    excluded = [tag for tag in rom.metadata.tags if tag in output.tag_excludes]
    if excluded:
        return False, [f"{_en_mayuscula(MOTIVO_TAG_EXCLUIDO)}: {', '.join(excluded)}"]
    if output.require_ra:
        reasons.append(f"Compatible con {MOTIVO_RA}")
    if output.strict_1g1r:
        reasons.append(f"Candidato de {MOTIVO_1G1R}")
    return True, reasons


def _rom_tags(rom: ScannedRom) -> set[str]:
    tags = set(rom.metadata.tags)
    if rom.dat_game:
        for name in filter(None, [rom.dat_game.name, rom.dat_game.description]):
            tags.update(parse_no_intro_name(name).tags)
    if rom.inner_path:
        tags.update(parse_no_intro_name(rom.inner_path).tags)
    return tags


def _strict_exclusions(rom: ScannedRom) -> list[str]:
    return sorted(_rom_tags(rom) & STRICT_1G1R_TAGS)


def _score(rom: ScannedRom, output: ProfileOutput, complete: set[str] | None = None) -> tuple:
    return (
        # Una variante que trae todos los discos gana a otra a la que le falte
        # alguno, aunque su región puntúe mejor. En juegos de un solo soporte
        # este término es siempre 0 y no cambia nada.
        0 if not rom.metadata.part or not complete or variant_key(rom) in complete else 1,
        priority_index(rom.metadata.regions, output.region_priority),
        priority_index(rom.metadata.languages, output.language_priority),
        0 if output.prefer_ra_compatible and rom.ra_game_id else 1,
        -rom.metadata.revision if output.prefer_newest_revision else rom.metadata.revision,
        0 if rom.dat_game else 1,
        rom.source_path.lower(),
    )


def _loss_reasons(rom: ScannedRom, winner: ScannedRom, output: ProfileOutput) -> list[str]:
    rom_region = priority_index(rom.metadata.regions, output.region_priority)
    winner_region = priority_index(winner.metadata.regions, output.region_priority)
    if rom_region != winner_region:
        return [
            f"Descartado por prioridad de {MOTIVO_REGION}",
            f"{', '.join(rom.metadata.regions) or 'desconocida'} pierde contra {', '.join(winner.metadata.regions) or 'desconocida'}",
        ]

    rom_language = priority_index(rom.metadata.languages, output.language_priority)
    winner_language = priority_index(winner.metadata.languages, output.language_priority)
    if rom_language != winner_language:
        return [
            f"Descartado por prioridad de {MOTIVO_IDIOMA}",
            f"{', '.join(rom.metadata.languages) or 'desconocido'} pierde contra {', '.join(winner.metadata.languages) or 'desconocido'}",
        ]

    rom_revision = rom.metadata.revision
    winner_revision = winner.metadata.revision
    if output.prefer_ra_compatible and bool(rom.ra_game_id) != bool(winner.ra_game_id):
        return [f"Descartado porque otro candidato cubre {MOTIVO_RA}"]
    if rom_revision != winner_revision:
        if output.prefer_newest_revision:
            return [f"Descartado por {MOTIVO_REVISION} más antigua", f"Rev {rom_revision} pierde contra Rev {winner_revision}"]
        return [f"Descartado por {MOTIVO_REVISION} más nueva", f"Rev {rom_revision} pierde contra Rev {winner_revision}"]

    if bool(rom.dat_game) != bool(winner.dat_game):
        return [f"Descartado porque otro candidato está {MOTIVO_DAT_OK}"]

    return [f"Menor prioridad que {Path(winner.source_path).name}"]


def _special_folder(rom: ScannedRom) -> str | None:
    for tag in rom.metadata.tags:
        folder = SPECIAL_TAG_FOLDERS.get(tag)
        if folder:
            return folder
    for tag in sorted(_rom_tags(rom)):
        folder = SPECIAL_TAG_FOLDERS.get(tag)
        if folder:
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


CONTAINER_EXPLANATION = {
    ContainerMode.EXTRACT: "Se extrae del contenedor como archivo suelto",
    ContainerMode.REZIP: "Entra en un ZIP nuevo con el resto de archivos del juego",
    ContainerMode.TORRENTZIP: "Entra en un ZIP canónico (TorrentZip) con el resto de archivos del juego",
}


def _rom_key(rom: ScannedRom) -> str:
    return f"{rom.container_path}|{rom.inner_path}" if rom.inner_path else rom.container_path


def member_name(rom: ScannedRom) -> str:
    """Nombre del archivo al salir de su contenedor.

    El del DAT cuando se conoce —es lo que hace que dos colecciones curadas se
    parezcan— y el que ya tenía cuando no.
    """
    from .renaming import expected_file_name

    return expected_file_name(rom) or Path(rom.inner_path or rom.container_path).name


def _archive_title(winner: ScannedRom) -> str:
    return winner.dat_game.name if winner.dat_game else winner.metadata.title


def _container_destination(
    output_dir: Path | None,
    rom: ScannedRom,
    winner: ScannedRom,
    output: ProfileOutput,
    action: ActionMode,
    layout: ExportLayout,
    container_mode: ContainerMode,
) -> str | None:
    """Ruta de destino según qué se haga con los contenedores.

    Con `keep` es el contenedor; con `extract`, el archivo suelto; con `rezip`,
    un ZIP por juego al que van todos sus archivos.
    """
    if container_mode in ARCHIVE_MODES:
        return _destination_path(output_dir, rom, output, action, layout, filename=f"{Path(_archive_title(winner)).stem}.zip")
    if container_mode == ContainerMode.EXTRACT:
        return _destination_path(output_dir, rom, output, action, layout, filename=member_name(rom))
    return _destination_path(output_dir, rom, output, action, layout)


def _patch_candidate_score(candidate: RaPatchCandidate, output: ProfileOutput) -> tuple:
    metadata = parse_no_intro_name(candidate.hash_name or candidate.title or "")
    return (
        priority_index(metadata.regions, output.region_priority),
        priority_index(metadata.languages, output.language_priority),
        -metadata.revision if output.prefer_newest_revision else metadata.revision,
        candidate.hash_name or "",
    )


def _patch_destination_name(candidate: RaPatchCandidate, base: ScannedRom) -> str:
    if candidate.hash_name:
        return Path(candidate.hash_name).name
    return f"{Path(base.container_path).stem} [RA patched]{Path(base.container_path).suffix}"


def variant_key(rom: ScannedRom) -> str:
    """Variante a la que pertenece el archivo, sin el soporte: 'FFVII (Europe)'."""
    return strip_part(rom.dat_game.name if rom.dat_game else Path(rom.source_path).stem)


def complete_variants(scan: ScanResult) -> set[str]:
    """Variantes que traen todos los soportes que hay del juego.

    Elegir disco a disco por prioridad de región puede dejar el disco 1 europeo
    junto al 2 americano, que no arranca. Si alguna variante está completa, se
    prefiere entera; si ninguna lo está, se conserva lo que haya y se avisa.
    """
    parts_by_title: dict[str, set[str]] = defaultdict(set)
    parts_by_variant: dict[str, set[str]] = defaultdict(set)
    for rom in scan.roms:
        if not rom.metadata.part:
            continue
        parts_by_title[rom.metadata.title].add(rom.metadata.part)
        parts_by_variant[variant_key(rom)].add(rom.metadata.part)
    return {
        variant_key(rom)
        for rom in scan.roms
        if rom.metadata.part and parts_by_variant[variant_key(rom)] >= parts_by_title[rom.metadata.title]
    }


def game_siblings(winner: ScannedRom, candidates: list[ScannedRom]) -> list[ScannedRom]:
    """Los demás archivos del mismo juego del DAT que el ganador.

    Un juego de Redump son varios archivos (un .cue y sus .bin), y el DAT los
    declara juntos en una sola entrada. Elegir una variante significa quedarse
    con todos sus archivos: quedarse solo con el mejor puntuado dejaba un .bin
    suelto sin su .cue, es decir, un juego que no arranca.
    """
    if winner.dat_game is None or len(winner.dat_game.roms) < 2:
        return []
    seen = {winner.hashes.md5}
    siblings: list[ScannedRom] = []
    for rom in candidates:
        if rom.id == winner.id or rom.dat_game is None or rom.dat_game.name != winner.dat_game.name:
            continue
        if rom.hashes.md5 in seen:  # copias del mismo archivo: basta una
            continue
        seen.add(rom.hashes.md5)
        siblings.append(rom)
    return siblings


def select_best(
    candidates: list[ScannedRom],
    output: ProfileOutput,
    override_rom_id: str | None = None,
    complete: set[str] | None = None,
) -> tuple[ScannedRom | None, list[CandidateDecision]]:
    rejected: list[tuple[ScannedRom, list[str]]] = []
    allowed: list[ScannedRom] = []
    for rom in candidates:
        ok, reasons = _allowed(rom, output)
        if ok:
            allowed.append(rom)
        else:
            rejected.append((rom, reasons))
    if not allowed:
        return None, [CandidateDecision(rom_id=rom.id, source_path=rom.source_path, kept=False, reasons=reasons) for rom, reasons in rejected]
    override = next((rom for rom in candidates if rom.id == override_rom_id), None) if override_rom_id else None
    winner = override if override else sorted(allowed, key=lambda rom: _score(rom, output, complete))[0]
    # Los demás archivos del juego ganador se conservan aunque un filtro del
    # perfil los rechazara: sin su .cue o sus pistas, el ganador no sirve.
    siblings = {rom.id for rom in game_siblings(winner, candidates)}
    sibling_reason = f"Archivo del juego elegido: {winner.dat_game.name}" if winner.dat_game else "Archivo del juego elegido"

    decisions: list[CandidateDecision] = []
    for rom, reasons in rejected:
        kept = rom.id in siblings
        decisions.append(CandidateDecision(rom_id=rom.id, source_path=rom.source_path, kept=kept, reasons=[sibling_reason] if kept else reasons))
    for rom in allowed:
        if rom.id == winner.id:
            reasons = [f"Seleccionado: {MOTIVO_OVERRIDE}" if override else "Seleccionado como mejor candidato", *explain_score(rom, output)]
        elif rom.id in siblings:
            reasons = [sibling_reason]
        else:
            reasons = [*_loss_reasons(rom, winner, output), *explain_score(rom, output)]
        decisions.append(CandidateDecision(rom_id=rom.id, source_path=rom.source_path, kept=rom.id == winner.id or rom.id in siblings, reasons=reasons))
    return winner, decisions


def _groups_for_output(scan: ScanResult, output: ProfileOutput) -> dict[str, list[ScannedRom]]:
    if platform_spec(scan.platform).kind == "arcade":
        return _arcade_groups_for_output(scan, output)
    title_to_parent_keys: dict[tuple[str, str], set[str]] = defaultdict(set)
    for rom in scan.roms:
        title_to_parent_keys[_title_and_part(rom)].add(rom.dat_game.group_key if rom.dat_game and rom.dat_game.cloneof else rom.metadata.title)

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


def _title_and_part(rom: ScannedRom) -> tuple[str, str]:
    return rom.metadata.title, rom.metadata.part or ""


def _selection_group_key(rom: ScannedRom, title_to_parent_keys: dict[tuple[str, str], set[str]]) -> str:
    """Grupo del que el 1G1R conserva una variante.

    Cada soporte va a su propio grupo: los discos de un mismo juego no son
    variantes alternativas entre las que elegir, sino piezas que hacen falta
    todas. Sin esto, de un juego de tres discos solo sobrevivía el primero.
    """
    if len(title_to_parent_keys.get(_title_and_part(rom), set())) > 1:
        base = rom.metadata.title
    elif rom.dat_game and rom.dat_game.cloneof:
        base = rom.dat_game.group_key
    else:
        base = rom.metadata.title
    return with_part(base, rom.metadata.part)


def _part_order(part: str) -> tuple[str, int, str]:
    """Ordena 'disc 2' antes que 'disc 10', y las caras por letra."""
    kind, _, value = part.partition(" ")
    return (kind, int(value) if value.isdigit() else 0, value)


def _build_playlists(manifest: Manifest, scan: ScanResult) -> list[ManifestPlaylist]:
    """Un .m3u por juego de varios discos y salida, con los discos en orden.

    Los emuladores guardan la partida contra el nombre del .m3u, así que sin él
    cada disco tiene su propio save y el juego no se puede terminar.
    """
    rom_by_id = {rom.id: rom for rom in scan.roms}
    grouped: dict[tuple[OutputBucket, str, str], dict[str, str]] = defaultdict(dict)
    for entry in manifest.entries:
        rom = rom_by_id.get(entry.rom_id)
        if rom is None or not rom.metadata.part or not entry.destination_path:
            continue
        destination = Path(entry.destination_path)
        grouped[(entry.bucket, str(destination.parent), rom.metadata.title)].setdefault(rom.metadata.part, destination.name)

    playlists: list[ManifestPlaylist] = []
    for (_bucket, folder, title), discos in sorted(grouped.items(), key=lambda item: (item[0][2].lower(), item[0][1])):
        if len(discos) < 2:  # un solo disco no necesita playlist
            continue
        ordenados = [name for _part, name in sorted(discos.items(), key=lambda item: _part_order(item[0]))]
        playlists.append(ManifestPlaylist(path=str(Path(folder) / f"{title}.m3u"), title=title, entries=ordenados))
    return playlists


def build_manifest(
    scan: ScanResult,
    profile: SelectionProfile,
    outputs: list[OutputBucket],
    output_dir: Path | None,
    action: ActionMode = ActionMode.COPY,
    overrides: dict[str, dict[str, str]] | None = None,
    ra_cache: Path | None = None,
    container_mode: ContainerMode = ContainerMode.KEEP,
) -> Manifest:
    manifest = Manifest(
        id=f"manifest-{scan.id}",
        scan_id=scan.id,
        platform=scan.platform,
        profile_snapshot=profile.model_dump(mode="json"),
    )
    selected_paths: set[tuple[OutputBucket, str]] = set()
    copied_main_paths: set[str] = set()
    winner_containers: set[str] = set()
    selected_buckets: list[OutputBucket] = []
    overrides = overrides or {}
    layout = profile.export_layout
    complete = complete_variants(scan)
    # Se construye a la primera que haga falta: consultarlo por grupo leía la
    # tabla entera de parches cada vez.
    patch_index: dict[str, list[RaPatchCandidate]] | None = None
    # Con rezip, los archivos de un juego van juntos a un ZIP nuevo, así que el
    # destino se comparte a propósito: lo que identifica una operación deja de
    # ser el contenedor y pasa a ser el archivo concreto.
    archives: dict[str, ManifestArchive] = {}
    for output in profile.outputs:
        if output.bucket not in outputs:
            continue
        selected_buckets.append(output.bucket)
        groups = _groups_for_output(scan, output)
        for group_key, candidates in groups.items():
            override_rom_id = overrides.get(output.bucket.value, {}).get(group_key)
            winner, decisions = select_best(candidates, output, override_rom_id=override_rom_id, complete=complete)
            manifest.discarded.extend(decisions)
            if not winner:
                if output.bucket == OutputBucket.RA and output.require_ra and profile.auto_patch_ra and action != ActionMode.DELETE:
                    base_output = output.model_copy(update={"require_ra": False})
                    base_winner, base_decisions = select_best(candidates, base_output, override_rom_id=override_rom_id, complete=complete)
                    manifest.discarded.extend(base_decisions)
                    if base_winner:
                        if patch_index is None:
                            patch_index = ra_patch_index(scan.platform, cache=ra_cache)
                        patch_candidates = sorted(patch_index.get(normalize_ra_title(base_winner.metadata.title), []), key=lambda candidate: _patch_candidate_score(candidate, output))
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
                                        f"Salida de {MOTIVO_RA} generada con un {MOTIVO_PARCHE}",
                                        f"URL del {MOTIVO_PARCHE}: {patch_candidate.patch_url}",
                                        f"MD5 RA esperado: {patch_candidate.md5}",
                                        f"Carpeta de la salida organizada: {_destination_folder(base_winner, output, layout)}",
                                        *explain_score(base_winner, base_output),
                                    ],
                                )
                            )
                continue
            # Un juego del DAT puede ser varios archivos (.cue + sus .bin): se
            # copian todos, no solo el que mejor puntuó.
            siblings = game_siblings(winner, candidates)
            for rom in (winner, *siblings):
                winner_containers.add(rom.container_path)
            if action == ActionMode.DELETE:
                continue
            for rom in (winner, *siblings):
                if layout == ExportLayout.ORGANIZED and output.bucket == OutputBucket.RA and rom.container_path in copied_main_paths:
                    continue
                key = (output.bucket, rom.container_path) if container_mode == ContainerMode.KEEP else (output.bucket, _rom_key(rom))
                if key in selected_paths:
                    continue
                selected_paths.add(key)
                if output.bucket == OutputBucket.MAIN:
                    copied_main_paths.add(rom.container_path)
                destination = _container_destination(output_dir, rom, winner, output, action, layout, container_mode)
                if container_mode in ARCHIVE_MODES and destination:
                    archive = archives.setdefault(
                        destination,
                        ManifestArchive(path=destination, title=_archive_title(winner), mode=container_mode),
                    )
                    archive.members.append(
                        ManifestArchiveMember(
                            source_path=rom.container_path,
                            source_inner_path=rom.inner_path,
                            name=member_name(rom),
                            md5=rom.hashes.md5,
                            size=rom.hashes.size,
                        )
                    )
                if rom.id == winner.id:
                    explanation = [f"Seleccionado: {MOTIVO_OVERRIDE}"] if override_rom_id == winner.id else ["Seleccionado como mejor candidato"]
                else:
                    explanation = [f"Archivo del juego elegido: {winner.dat_game.name}" if winner.dat_game else "Archivo del juego elegido"]
                if layout == ExportLayout.ORGANIZED:
                    explanation.append(f"Carpeta de la salida organizada: {_destination_folder(rom, output, layout)}")
                if container_mode != ContainerMode.KEEP and rom.inner_path:
                    explanation.append(CONTAINER_EXPLANATION[container_mode])
                if output.require_ra:
                    explanation.append(f"La salida de {MOTIVO_RA} exige un hash que coincida")
                if rom.ra_patch_url or "rapatches" in {label.lower() for label in rom.ra_labels}:
                    explanation.append(f"Metadatos de {MOTIVO_PARCHE} de {MOTIVO_RA}: {rom.ra_patch_url or 'rapatches'}")
                if rom.dat_game:
                    explanation.append(f"{_en_mayuscula(MOTIVO_DAT_COINCIDE)}: {rom.dat_game.name}")
                if rom.id == winner.id:
                    explanation.extend(explain_score(rom, output))
                manifest.entries.append(
                    ManifestEntry(
                        bucket=output.bucket,
                        action=action,
                        source_path=rom.container_path,
                        source_inner_path=rom.inner_path if container_mode != ContainerMode.KEEP else None,
                        # Con un contenedor, el MD5 del archivo de origen no es
                        # el de la ROM; al extraer, lo que se escribe sí es la
                        # ROM, así que ahí su MD5 es justo lo que hay que
                        # verificar.
                        source_md5=rom.hashes.md5 if rom.inner_path is None or container_mode != ContainerMode.KEEP else None,
                        source_size=rom.hashes.size,
                        container_mode=container_mode,
                        destination_path=destination,
                        rom_id=rom.id,
                        dat_name=rom.dat_game.name if rom.dat_game else None,
                        ra_game_id=rom.ra_game_id,
                        explanation=explanation,
                    )
                )
    if action != ActionMode.DELETE:
        manifest.archives = [archives[clave] for clave in sorted(archives)]
        manifest.playlists = _build_playlists(manifest, scan)
    if action == ActionMode.DELETE and selected_buckets:
        discard_reasons: dict[str, list[str]] = {}
        for decision in manifest.discarded:
            if not decision.kept:
                discard_reasons.setdefault(decision.rom_id, decision.reasons)
        delete_bucket = selected_buckets[0]
        seen_containers: set[str] = set()
        for rom in scan.roms:
            container = rom.container_path
            if container in winner_containers or container in seen_containers:
                continue
            seen_containers.add(container)
            manifest.entries.append(
                ManifestEntry(
                    bucket=delete_bucket,
                    action=ActionMode.DELETE,
                    source_path=container,
                    rom_id=rom.id,
                    dat_name=rom.dat_game.name if rom.dat_game else None,
                    ra_game_id=rom.ra_game_id,
                    explanation=["Borrar descartado: ninguna salida seleccionada lo conserva", *discard_reasons.get(rom.id, [])],
                )
            )
    return manifest
