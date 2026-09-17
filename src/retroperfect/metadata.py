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


# Soportes de un juego repartido en varias piezas. No-Intro y Redump usan
# "(Disc 2)"; TOSEC añade "of" ("Disk 1 of 3") y los ordenadores de cinta y
# disquete usan caras y cintas numeradas.
_PART_PATTERN = re.compile(
    r"^(?P<kind>dis[ck]|cd|dvd|gd|side|tape|cassette|casete|cara|cinta|disco)\s*(?P<number>[0-9]+|[a-z])(?:\s+(?:of|de)\s+[0-9]+)?$",
    re.I,
)
# Un mismo soporte se nombra de varias formas según el catálogo; se unifican
# para que "(Disk 2)" y "(Disc 2)" no acaben en grupos distintos.
_PART_ALIASES = {"disk": "disc", "disco": "disc", "cd": "disc", "dvd": "disc", "gd": "disc", "cara": "side", "cassette": "tape", "casete": "tape", "cinta": "tape"}


def detect_part(text: str) -> str | None:
    """Normaliza un soporte a la forma 'disc 2' o 'side a', o None si no lo es."""
    match = _PART_PATTERN.match(text.strip())
    if not match:
        return None
    kind = match.group("kind").lower()
    return f"{_PART_ALIASES.get(kind, kind)} {match.group('number').lower()}"


_PART_GROUP = re.compile(
    r"\s*[\(\[](?:dis[ck]|cd|dvd|gd|side|tape|cassette|casete|cara|cinta|disco)\s*(?:[0-9]+|[a-z])(?:\s+(?:of|de)\s+[0-9]+)?[\)\]]",
    re.I,
)


def strip_part(name: str) -> str:
    """Quita el soporte del nombre: 'FFVII (Europe) (Disc 2)' → 'FFVII (Europe)'.

    Sirve para saber a qué variante pertenece cada pieza, y así preferir la que
    tenga todos los discos antes que mezclar regiones en un mismo juego.
    """
    return _PART_GROUP.sub("", name).strip()


def with_part(base: str, part: str | None) -> str:
    """Añade el soporte a una clave de agrupación.

    Lo usan la curación, la cobertura, la descarga y la pestaña Decisiones: si
    cada una compusiera la clave a su manera, los overrides manuales dejarían
    de casar con los grupos del manifiesto.
    """
    return f"{base} · {part}" if part else base


def parse_no_intro_name(name: str) -> DetectedMetadata:
    stem = Path(name).stem
    title = re.sub(r"\s*[\(\[].*?[\)\]]", "", stem).strip()
    groups = re.findall(r"[\(\[]([^\)\]]+)[\)\]]", stem)
    part: str | None = None
    regions: list[str] = []
    languages: list[str] = []
    tags: list[str] = []
    version: str | None = None
    revision = 0

    for group in groups:
        parts = [p.strip() for p in re.split(r",|/|\+", group) if p.strip()]
        for part_text in parts:
            part_text = re.sub(r"\s+", " ", part_text).strip()
            if part is None:
                part = detect_part(part_text)
            normalized = REGION_ALIASES.get(part_text)
            if normalized and normalized not in regions:
                regions.append(normalized)
            language = LANGUAGE_ALIASES.get(part_text)
            if language and language not in languages:
                languages.append(language)
            rev_match = re.search(r"(?:Rev(?:ision)?|Version)\s*([A-Za-z0-9.]+)|\bv([0-9][A-Za-z0-9.]*)", part_text, re.I)
            if rev_match:
                version = rev_match.group(1) or rev_match.group(2)
                digits = re.findall(r"\d+", version)
                if digits:
                    revision = int(digits[-1])
                elif len(version) == 1 and version.isalpha():
                    revision = ord(version.upper()) - ord("A") + 1
            for keyword in TAG_KEYWORDS:
                if keyword not in tags and re.search(rf"\b{re.escape(keyword)}\b", part_text, re.I):
                    tags.append(keyword)
        languages_found = re.findall(r"\b(En|Es|Ja|Jp|Fr|De|It|Pt|Nl|Sv)\b", group)
        if len(languages_found) >= 2 and "Multi" not in languages:
            languages.append("Multi")

    return DetectedMetadata(title=title or stem, regions=regions, languages=languages, version=version, revision=revision, tags=tags, part=part)
