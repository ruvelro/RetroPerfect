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
    "platform_from_dat_name",
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


def platform_from_dat_name(name: str) -> Platform | None:
    lowered = name.lower()
    for spec in list_platforms():
        if any(alias.lower() in lowered for alias in spec.dat_aliases):
            return spec.id
    return None
