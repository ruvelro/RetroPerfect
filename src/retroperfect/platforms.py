from __future__ import annotations

from .models import Platform
from .platforms_data import (
    ARCADE_EXTENSIONS,
    CD_EXTENSIONS,
    DIGITAL_EXTENSIONS,
    DISK_EXTENSIONS,
    PLATFORM_SPECS,
    PRIORITY_PLATFORMS,
    RA_CONSOLE_IDS,
    RA_ICON_URLS,
    PlatformSpec,
)

__all__ = [
    "ARCADE_EXTENSIONS",
    "CD_EXTENSIONS",
    "DIGITAL_EXTENSIONS",
    "DISK_EXTENSIONS",
    "PLATFORM_SPECS",
    "PRIORITY_PLATFORMS",
    "RA_CONSOLE_IDS",
    "RA_ICON_URLS",
    "PlatformSpec",
    "list_platforms",
    "FOLDER_ALIASES",
    "platform_from_dat_name",
    "platform_from_folder_name",
    "platform_options",
    "platform_spec",
]


def platform_spec(platform: Platform | str) -> PlatformSpec:
    parsed = Platform(platform)
    return PLATFORM_SPECS[parsed]


def list_platforms() -> list[PlatformSpec]:
    return [PLATFORM_SPECS[item] for item in PRIORITY_PLATFORMS]


def platform_options() -> dict[str, str]:
    return {spec.id.value: f"{spec.short_name} · {spec.brand}" for spec in list_platforms()}


# Nombres con los que la gente llama a sus carpetas y que no salen del catálogo.
# Solo se añade lo que es inequívoco: adivinar mal una plataforma hace que el
# escaneo no case con ningún DAT y el usuario no sepa por qué.
FOLDER_ALIASES = {
    "famicom": Platform.NES,
    "nintendo": Platform.NES,
    "sfc": Platform.SNES,
    "superfamicom": Platform.SNES,
    "supernintendo": Platform.SNES,
    "gameboy": Platform.GB,
    "gameboycolor": Platform.GBC,
    "gameboyadvance": Platform.GBA,
    "gba": Platform.GBA,
    "nintendo64": Platform.N64,
    "nintendods": Platform.NDS,
    "megadrive": Platform.MD,
    "genesis": Platform.MD,
    "segagenesis": Platform.MD,
    "mastersystem": Platform.SMS,
    "gamegear": Platform.GG,
    "megacd": Platform.SEGACD,
    "segacd": Platform.SEGACD,
    "playstation": Platform.PS1,
    "psx": Platform.PS1,
    "psone": Platform.PS1,
    "playstation2": Platform.PS2,
    "ps2": Platform.PS2,
    "playstationportable": Platform.PSP,
    "turbografx": Platform.PCE,
    "turbografx16": Platform.PCE,
    "pcengine": Platform.PCE,
    "neogeo": Platform.NEOGEO_MVS,
    "atari2600": Platform.A2600,
    "atari7800": Platform.A7800,
    "dreamcast": Platform.DREAMCAST,
    "saturn": Platform.SATURN,
    "gamecube": Platform.GAMECUBE,
    "ngc": Platform.GAMECUBE,
    "wii": Platform.WII,
    "spectrum": Platform.ZX_SPECTRUM,
    "zxspectrum": Platform.ZX_SPECTRUM,
    "commodore64": Platform.C64,
    "amstrad": Platform.CPC,
    "arcade": Platform.MAME,
    "mame": Platform.MAME,
    "fba": Platform.FBNEO,
    "fbneo": Platform.FBNEO,
}


def _folder_key(name: str) -> str:
    return "".join(char for char in name.casefold() if char.isalnum())


def platform_from_folder_name(name: str) -> Platform | None:
    """Plataforma de una carpeta de romset por su nombre, o None si no está claro.

    Se prueba el identificador exacto, el nombre corto del catálogo, el alias
    del DAT y una lista de nombres habituales (`psx`, `megadrive`, `sfc`...).
    Cuando nada encaja se devuelve None y quien llama lo reporta: dar por buena
    una plataforma equivocada hace que el escaneo no case con ningún DAT y el
    usuario no tenga forma de saber por qué.
    """
    clave = _folder_key(name)
    if not clave:
        return None
    for spec in list_platforms():
        if clave == _folder_key(spec.id.value):
            return spec.id
    if clave in FOLDER_ALIASES:
        return FOLDER_ALIASES[clave]
    for spec in list_platforms():
        if clave == _folder_key(spec.short_name) or clave == _folder_key(spec.name):
            return spec.id
    for spec in list_platforms():
        if any(clave == _folder_key(alias) for alias in spec.dat_aliases):
            return spec.id
    return None


def platform_from_dat_name(name: str) -> Platform | None:
    lowered = name.lower()
    for spec in list_platforms():
        if any(alias.lower() in lowered for alias in spec.dat_aliases):
            return spec.id
    return None
