"""Catálogo de plataformas, DATs instalados y estado de RetroAchievements."""
from __future__ import annotations

from ..dat_manager import list_installed_dats
from ..dat_sources import DAT_SOURCES
from ..models import Platform
from ..platforms import list_platforms, platform_spec
from ..ra import ra_cache_count, ra_sync_status


def _source_suffixes() -> set[str]:
    suffixes = {".zip", ".7z"}
    for spec in list_platforms():
        suffixes.update(spec.rom_extensions)
    return suffixes


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
