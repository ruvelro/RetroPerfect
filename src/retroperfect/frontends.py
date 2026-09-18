"""Exportación a frontends: playlists de RetroArch y gamelist de EmulationStation.

RetroPerfect termina con una colección verificada por hash contra el DAT, y sin
esto el usuario tiene que dejar que el frontend la re-escanee con su propia base
de datos, que es peor. Aquí se escribe directamente lo que el frontend consume,
con el nombre que dice el DAT y el CRC que ya se calculó.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .metadata import parse_no_intro_name
from .models import Manifest, Platform, ScannedRom, ScanResult
from .platforms import platform_spec

# RetroArch acepta DETECT para que elija el núcleo el propio programa. Mantener
# una tabla de núcleos por plataforma envejecería mal y no aporta: el usuario ya
# tiene su núcleo preferido configurado.
DETECT = "DETECT"


def libretro_system(platform: Platform) -> str:
    """Nombre del sistema tal y como lo nombran Libretro y los DAT de No-Intro."""
    alias = platform_spec(platform).dat_aliases[0]
    return LIBRETRO_SYSTEM_OVERRIDES.get(platform.value, alias.removeprefix("Non-Redump - ").removeprefix("Unofficial - "))


# Plataformas cuyo alias de DAT no coincide con el nombre que usa Libretro.
LIBRETRO_SYSTEM_OVERRIDES = {
    "fds": "Nintendo - Family Computer Disk System",
    "gamecube": "Nintendo - GameCube",
    "saturn": "Sega - Saturn",
    "pce-cd": "NEC - PC Engine CD - TurboGrafx-CD",
    "atomiswave": "Atomiswave",
    "neogeo-mvs": "SNK - Neo Geo",
    "psp-psn": "Sony - PlayStation Portable",
}


def _exported_roms(scan: ScanResult, manifest: Manifest | None) -> list[tuple[ScannedRom, Path]]:
    """ROMs a listar y su ruta final: la del plan si lo hay, y si no la actual."""
    if manifest is None:
        return [(rom, Path(rom.container_path)) for rom in scan.roms]
    rom_by_id = {rom.id: rom for rom in scan.roms}
    salidas: list[tuple[ScannedRom, Path]] = []
    vistos: set[str] = set()
    for entry in manifest.entries:
        rom = rom_by_id.get(entry.rom_id)
        if rom is None or not entry.destination_path or entry.destination_path in vistos:
            continue
        vistos.add(entry.destination_path)
        salidas.append((rom, Path(entry.destination_path)))
    return salidas


def _label(rom: ScannedRom) -> str:
    """Nombre del DAT sin extensión: es el que casa con las carátulas de Libretro."""
    if rom.dat_game:
        return Path(rom.dat_game.description or rom.dat_game.name).stem
    return Path(rom.container_path).stem


def _playlist_paths(manifest: Manifest | None) -> dict[str, str]:
    """Playlists por carpeta y título, para listar el .m3u en vez de cada disco."""
    return {f"{Path(playlist.path).parent}|{playlist.title}": playlist.path for playlist in (manifest.playlists if manifest else [])}


def build_retroarch_playlist(scan: ScanResult, manifest: Manifest | None = None) -> dict:
    """Playlist .lpl de RetroArch (JSON desde la 1.7.5).

    Los juegos de varios discos se listan por su .m3u, no disco a disco: es lo
    que hace que el emulador los trate como un solo juego.
    """
    sistema = libretro_system(scan.platform)
    playlists = _playlist_paths(manifest)
    items: list[dict[str, str]] = []
    vistos: set[str] = set()
    for rom, destino in _exported_roms(scan, manifest):
        ruta = destino
        etiqueta = _label(rom)
        if rom.metadata.part:
            clave = f"{destino.parent}|{rom.metadata.title}"
            if clave in playlists:
                ruta = Path(playlists[clave])
                etiqueta = rom.metadata.title
        if str(ruta) in vistos:
            continue
        vistos.add(str(ruta))
        # Un .m3u no tiene CRC propio: agrupa varios archivos, así que va a cero
        # como hace el propio RetroArch al generar sus playlists.
        es_playlist = ruta != destino
        crc = "00000000|crc" if es_playlist else f"{rom.hashes.crc32.upper()}|crc"
        items.append(
            {
                "path": str(ruta),
                "label": etiqueta,
                "core_path": DETECT,
                "core_name": DETECT,
                "crc32": crc,
                "db_name": f"{sistema}.lpl",
            }
        )
    items.sort(key=lambda item: item["label"].lower())
    return {"version": "1.5", "default_core_path": "", "default_core_name": "", "label_display_mode": 0, "right_thumbnail_mode": 0, "left_thumbnail_mode": 0, "sort_mode": 0, "items": items}


def write_retroarch_playlist(scan: ScanResult, path: Path, manifest: Manifest | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_retroarch_playlist(scan, manifest), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_gamelist(scan: ScanResult, path: Path, manifest: Manifest | None = None) -> Path:
    """gamelist.xml de EmulationStation/Batocera, fusionando con el existente.

    Nunca se sobrescribe entero: ahí viven los favoritos y las horas jugadas del
    usuario, que no los pone RetroPerfect y no puede recuperarlos.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    raiz = _load_gamelist(path)
    existentes = {nodo.findtext("path", ""): nodo for nodo in raiz.findall("game")}
    playlists = _playlist_paths(manifest)

    for rom, destino in _exported_roms(scan, manifest):
        ruta, etiqueta = destino, _label(rom)
        if rom.metadata.part:
            clave = f"{destino.parent}|{rom.metadata.title}"
            if clave in playlists:
                ruta, etiqueta = Path(playlists[clave]), rom.metadata.title
        relativa = f"./{ruta.name}"
        nodo = existentes.get(relativa)
        if nodo is None:
            nodo = ET.SubElement(raiz, "game")
            ET.SubElement(nodo, "path").text = relativa
            existentes[relativa] = nodo
        _set_text(nodo, "name", etiqueta)
        metadata = parse_no_intro_name(rom.dat_game.name if rom.dat_game else ruta.name)
        if metadata.regions:
            _set_text(nodo, "region", metadata.regions[0])
        if metadata.languages:
            _set_text(nodo, "lang", metadata.languages[0])

    ET.indent(raiz, space="  ")
    path.write_text('<?xml version="1.0"?>\n' + ET.tostring(raiz, encoding="unicode") + "\n", encoding="utf-8")
    return path


def _load_gamelist(path: Path) -> ET.Element:
    if not path.exists():
        return ET.Element("gameList")
    try:
        raiz = ET.parse(path).getroot()
    except ET.ParseError:
        # Un gamelist corrupto no se pisa en silencio: se conserva a un lado.
        path.rename(path.with_suffix(".xml.roto"))
        return ET.Element("gameList")
    return raiz if raiz.tag == "gameList" else ET.Element("gameList")


def _set_text(nodo: ET.Element, etiqueta: str, valor: str) -> None:
    hijo = nodo.find(etiqueta)
    if hijo is None:
        hijo = ET.SubElement(nodo, etiqueta)
    hijo.text = valor
