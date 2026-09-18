"""Carátulas de Libretro, emparejadas por el nombre exacto del DAT.

Esto no es scraping: los thumbnails de Libretro están nombrados igual que las
entradas de No-Intro y Redump, con una única sustitución documentada de
caracteres. No hace falta clave de API, cuenta ni heurística de títulos, y por
eso encaja con la regla de la casa de emparejar por dato exacto y no por
parecido. Lo que no esté, se dice; no se baja una carátula aproximada.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .frontends import libretro_system
from .http import http_get
from .models import Manifest, Platform, ScanResult

BASE_URL = "https://thumbnails.libretro.com"

# Las tres carpetas que publica Libretro por sistema.
KINDS = {
    "boxart": "Named_Boxarts",
    "snap": "Named_Snaps",
    "title": "Named_Titles",
}

# Sustitución que aplica Libretro al nombrar los archivos.
_PROHIBIDOS = '&*/:`<>?\\|"'


@dataclass
class ThumbnailOutcome:
    title: str
    kind: str
    status: str  # ok | presente | ausente | error
    path: str = ""
    detail: str = ""


def thumbnail_name(dat_name: str) -> str:
    """Nombre del archivo de carátula para una entrada del DAT."""
    stem = Path(dat_name).stem
    return "".join("_" if char in _PROHIBIDOS else char for char in stem)


def thumbnail_url(platform: Platform, dat_name: str, kind: str) -> str:
    sistema = libretro_system(platform)
    return f"{BASE_URL}/{quote(sistema)}/{KINDS[kind]}/{quote(thumbnail_name(dat_name))}.png"


def has_thumbnails(platform: Platform) -> bool:
    """Si Libretro publica carátulas para esta plataforma."""
    return libretro_system(platform) in LIBRETRO_THUMBNAIL_SYSTEMS


def download_thumbnails(
    scan: ScanResult,
    destination: Path,
    *,
    manifest: Manifest | None = None,
    kinds: tuple[str, ...] = ("boxart",),
    limit: int | None = None,
    overwrite: bool = False,
    progress=None,
) -> list[ThumbnailOutcome]:
    """Descarga las carátulas de los juegos identificados contra el DAT.

    Solo se piden las de ROMs con coincidencia en el DAT: sin nombre oficial no
    hay emparejamiento exacto, y adivinar es justo lo que no queremos.
    """
    if not has_thumbnails(scan.platform):
        return [ThumbnailOutcome(title="", kind="", status="error", detail=f"Libretro no publica carátulas de {libretro_system(scan.platform)}.")]

    juegos: dict[str, str] = {}
    permitidos = _exported_dat_names(manifest)
    for rom in scan.roms:
        if rom.dat_game is None:
            continue
        nombre = rom.dat_game.description or rom.dat_game.name
        if permitidos is not None and rom.dat_game.name not in permitidos:
            continue
        juegos.setdefault(Path(nombre).stem, nombre)

    resultados: list[ThumbnailOutcome] = []
    pendientes = sorted(juegos.items())[: limit or None]
    total = len(pendientes) * len(kinds)
    for indice, (titulo, nombre_dat) in enumerate(pendientes, start=1):
        for kind in kinds:
            if progress:
                progress({"current": (indice - 1) * len(kinds) + 1, "total": total, "title": titulo})
            resultados.append(_descargar_una(scan.platform, titulo, nombre_dat, kind, destination, overwrite))
    return resultados


def _exported_dat_names(manifest: Manifest | None) -> set[str] | None:
    """Nombres del DAT que el plan conserva, o None para no filtrar."""
    if manifest is None:
        return None
    return {entry.dat_name for entry in manifest.entries if entry.dat_name}


def _descargar_una(platform: Platform, titulo: str, nombre_dat: str, kind: str, destination: Path, overwrite: bool) -> ThumbnailOutcome:
    carpeta = destination / KINDS[kind]
    destino = carpeta / f"{thumbnail_name(nombre_dat)}.png"
    if destino.exists() and not overwrite:
        return ThumbnailOutcome(title=titulo, kind=kind, status="presente", path=str(destino))
    try:
        respuesta = http_get(thumbnail_url(platform, nombre_dat, kind))
    except Exception as error:  # noqa: BLE001 - una carátula que falla no corta la tanda
        return ThumbnailOutcome(title=titulo, kind=kind, status="error", detail=str(error))
    if respuesta.status_code == 404:
        return ThumbnailOutcome(title=titulo, kind=kind, status="ausente", detail="Libretro no tiene esta carátula.")
    if respuesta.status_code >= 400:
        return ThumbnailOutcome(title=titulo, kind=kind, status="error", detail=f"HTTP {respuesta.status_code}")
    carpeta.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(respuesta.content)
    return ThumbnailOutcome(title=titulo, kind=kind, status="ok", path=str(destino))


# Sistemas con carpeta de carátulas en thumbnails.libretro.com. Se comprueba
# antes de pedir nada: así una plataforma sin carátulas lo dice en vez de
# devolver 404 juego por juego.
LIBRETRO_THUMBNAIL_SYSTEMS = frozenset({
    "Amstrad - CPC",
    "Amstrad - GX4000",
    "Arduboy Inc - Arduboy",
    "Atari - 2600",
    "Atari - 5200",
    "Atari - 7800",
    "Atari - 8-bit",
    "Atari - Jaguar",
    "Atari - Lynx",
    "Atari - ST",
    "Atomiswave",
    "Bandai - WonderSwan",
    "Bandai - WonderSwan Color",
    "Cannonball",
    "Casio - Loopy",
    "Casio - PV-1000",
    "Cave Story",
    "ChaiLove",
    "Coleco - ColecoVision",
    "Commodore - 64",
    "Commodore - Amiga",
    "Commodore - CD32",
    "Commodore - CDTV",
    "Commodore - PET",
    "Commodore - Plus-4",
    "Commodore - VIC-20",
    "DOOM",
    "DOS",
    "Dinothawr",
    "Emerson - Arcadia 2001",
    "Entex - Adventure Vision",
    "Epoch - Super Cassette Vision",
    "FBNeo - Arcade Games",
    "Fairchild - Channel F",
    "Flashback",
    "Funtech - Super Acan",
    "GCE - Vectrex",
    "GamePark - GP32",
    "Handheld Electronic Game",
    "Hartung - Game Master",
    "Jump 'n Bump",
    "LeapFrog - Leapster Learning Game System",
    "LowRes NX",
    "Lutro",
    "MAME",
    "Magnavox - Odyssey2",
    "Mattel - Intellivision",
    "Microsoft - MSX",
    "Microsoft - MSX2",
    "Microsoft - Xbox",
    "Microsoft - Xbox 360",
    "MrBoom",
    "NEC - PC Engine - TurboGrafx 16",
    "NEC - PC Engine CD - TurboGrafx-CD",
    "NEC - PC Engine SuperGrafx",
    "NEC - PC-8001 - PC-8801",
    "NEC - PC-98",
    "NEC - PC-FX",
    "Nintendo - Family Computer Disk System",
    "Nintendo - Game Boy",
    "Nintendo - Game Boy Advance",
    "Nintendo - Game Boy Color",
    "Nintendo - GameCube",
    "Nintendo - Nintendo 3DS",
    "Nintendo - Nintendo 64",
    "Nintendo - Nintendo 64DD",
    "Nintendo - Nintendo DS",
    "Nintendo - Nintendo DSi",
    "Nintendo - Nintendo Entertainment System",
    "Nintendo - Pokemon Mini",
    "Nintendo - Satellaview",
    "Nintendo - Sufami Turbo",
    "Nintendo - Super Nintendo Entertainment System",
    "Nintendo - Virtual Boy",
    "Nintendo - Wii",
    "Nintendo - Wii U",
    "Philips - CD-i",
    "Philips - Videopac+",
    "Quake",
    "Quake II",
    "Quake III",
    "RCA - Studio II",
    "RPG Maker",
    "Rick Dangerous",
    "SNK - Neo Geo",
    "SNK - Neo Geo CD",
    "SNK - Neo Geo Pocket",
    "SNK - Neo Geo Pocket Color",
    "ScummVM",
    "Sega - 32X",
    "Sega - Dreamcast",
    "Sega - Game Gear",
    "Sega - Master System - Mark III",
    "Sega - Mega Drive - Genesis",
    "Sega - Mega-CD - Sega CD",
    "Sega - Naomi",
    "Sega - Naomi 2",
    "Sega - PICO",
    "Sega - SG-1000",
    "Sega - Saturn",
    "Sharp - X1",
    "Sharp - X68000",
    "Sinclair - ZX 81",
    "Sinclair - ZX Spectrum",
    "Sony - PlayStation",
    "Sony - PlayStation 2",
    "Sony - PlayStation 3",
    "Sony - PlayStation 4",
    "Sony - PlayStation Portable",
    "Sony - PlayStation Vita",
    "Spectravideo - SVI-318 - SVI-328",
    "TIC-80",
    "The 3DO Company - 3DO",
    "Thomson - MOTO",
    "Tiger - Game.com",
    "Tomb Raider",
    "VTech - CreatiVision",
    "VTech - V.Smile",
    "Vircon32",
    "WASM-4",
    "Watara - Supervision",
    "Wolfenstein 3D"})
