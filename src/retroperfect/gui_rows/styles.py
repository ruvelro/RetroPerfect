"""Clases CSS, etiquetas y formateadores de presentación de la GUI."""
from __future__ import annotations

from pathlib import Path

from ..models import ActionMode
from ..paths import project_state_dir

ACTION_LABELS = {
    ActionMode.COPY.value: "Copiar archivos",
    ActionMode.MOVE.value: "Mover archivos",
    ActionMode.DELETE.value: "Borrar archivos",
}


def _page_class() -> str:
    return "max-w-screen-2xl mx-auto w-full px-4 py-4"


def _panel_class() -> str:
    return "rp-panel border border-gray-200 rounded-md p-4 w-full"


def _latest_project_path() -> Path:
    return project_state_dir() / "project.json"


FLAGS = {
    "Spain": "🇪🇸",
    "Europe": "🇪🇺",
    "USA": "🇺🇸",
    "Japan": "🇯🇵",
    "World": "🌐",
    "Asia": "🌏",
    "Brazil": "🇧🇷",
    "China": "🇨🇳",
    "Korea": "🇰🇷",
    "Germany": "🇩🇪",
    "France": "🇫🇷",
    "Italy": "🇮🇹",
    "Australia": "🇦🇺",
    "Taiwan": "🇹🇼",
}


def _flag_regions(regions: list[str]) -> str:
    return ", ".join(f"{FLAGS.get(region, '🏳️')} {region}" for region in regions)


def _ra_icon(rom) -> str:
    if not rom.ra_game_id:
        return ""
    icons = ["🏆"]
    if rom.ra_patch_url or "rapatches" in {label.lower() for label in rom.ra_labels}:
        icons.append("🩹")
    return " ".join(icons)
