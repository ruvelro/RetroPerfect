from __future__ import annotations

import re
from pathlib import Path

from .models import DetectedMetadata


REGION_ALIASES = {
    "E": "Europe",
    "EU": "Europe",
    "EUR": "Europe",
    "Europe": "Europe",
    "Spain": "Spain",
    "Es": "Spain",
    "USA": "USA",
    "US": "USA",
    "U": "USA",
    "World": "World",
    "Japan": "Japan",
    "JP": "Japan",
    "J": "Japan",
    "Brazil": "Brazil",
    "Brasil": "Brazil",
    "Australia": "Australia",
    "Asia": "Asia",
    "China": "China",
    "Hong Kong": "Hong Kong",
    "Taiwan": "Taiwan",
    "Germany": "Germany",
    "France": "France",
    "Italy": "Italy",
    "Netherlands": "Netherlands",
    "Sweden": "Sweden",
}

LANGUAGE_ALIASES = {
    "En": "English",
    "English": "English",
    "Es": "Spanish",
    "Spanish": "Spanish",
    "Ja": "Japanese",
    "Jp": "Japanese",
    "Japanese": "Japanese",
    "Fr": "French",
    "French": "French",
    "De": "German",
    "German": "German",
    "It": "Italian",
    "Italian": "Italian",
    "Pt": "Portuguese",
    "Portuguese": "Portuguese",
    "Nl": "Dutch",
    "Dutch": "Dutch",
    "Sv": "Swedish",
    "Swedish": "Swedish",
    "Multi": "Multi",
    "Multilanguage": "Multi",
}

TAG_KEYWORDS = {
    "Beta",
    "Proto",
    "Prototype",
    "Demo",
    "Sample",
    "Aftermarket",
    "Homebrew",
    "Unl",
    "Pirate",
    "Hack",
    "Bad",
    "Overdump",
    "Virtual Console",
    "Switch Online",
    "Nintendo Switch Online",
    "Retro-Bit Generations",
    "Anniversary Collection",
    "Castlevania Anniversary Collection",
    "Contra Anniversary Collection",
    "Disney Afternoon Collection",
    "Namcot Collection",
    "Classic Mini",
    "Program",
    "Kiosk",
    "Promo",
    "Trainer",
    "Translation",
    "Unlicensed",
}


def parse_no_intro_name(name: str) -> DetectedMetadata:
    stem = Path(name).stem
    title = re.sub(r"\s*[\(\[].*?[\)\]]", "", stem).strip()
    groups = re.findall(r"[\(\[]([^\)\]]+)[\)\]]", stem)
    regions: list[str] = []
    languages: list[str] = []
    tags: list[str] = []
    version: str | None = None
    revision = 0

    for group in groups:
        parts = [p.strip() for p in re.split(r",|/|\+", group) if p.strip()]
        for part in parts:
            part = re.sub(r"\s+", " ", part).strip()
            normalized = REGION_ALIASES.get(part)
            if normalized and normalized not in regions:
                regions.append(normalized)
            language = LANGUAGE_ALIASES.get(part)
            if language and language not in languages:
                languages.append(language)
            rev_match = re.search(r"(?:Rev(?:ision)?|Version)\s*([A-Za-z0-9.]+)|\bv([0-9][A-Za-z0-9.]*)", part, re.I)
            if rev_match:
                version = rev_match.group(1) or rev_match.group(2)
                digits = re.findall(r"\d+", version)
                if digits:
                    revision = int(digits[-1])
                elif len(version) == 1 and version.isalpha():
                    revision = ord(version.upper()) - ord("A") + 1
            for keyword in TAG_KEYWORDS:
                if keyword.lower() in part.lower() and keyword not in tags:
                    tags.append(keyword)
        languages_found = re.findall(r"\b(En|Es|Ja|Jp|Fr|De|It|Pt|Nl|Sv)\b", group)
        if len(languages_found) >= 2 and "Multi" not in languages:
            languages.append("Multi")

    return DetectedMetadata(title=title or stem, regions=regions, languages=languages, version=version, revision=revision, tags=tags)
