from __future__ import annotations

import re
from pathlib import Path

from .models import DetectedMetadata

# Regiones tal y como las nombran No-Intro, Redump y TOSEC, más las
# abreviaturas de los catálogos antiguos. La lista está completa a propósito:
# una región que no se reconozca no es un detalle cosmético, deja la ROM como
# "región desconocida" y la hace perder el 1G1R contra cualquier otra sin que
# el usuario vea el motivo. Faltaban Korea, Portugal y los países nórdicos, que
# sí aparecían en EUROPEAN_REGIONS y REGION_FOLDERS (rules.py) sin poder
# llegar nunca.
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
    "Korea": "Korea",
    "K": "Korea",
    "Germany": "Germany",
    "France": "France",
    "Italy": "Italy",
    "Netherlands": "Netherlands",
    "Sweden": "Sweden",
    "Denmark": "Denmark",
    "Norway": "Norway",
    "Finland": "Finland",
    "Portugal": "Portugal",
    "Scandinavia": "Scandinavia",
    "Austria": "Austria",
    "Belgium": "Belgium",
    "Switzerland": "Switzerland",
    "Ireland": "Ireland",
    "UK": "UK",
    "United Kingdom": "UK",
    "Greece": "Greece",
    "Poland": "Poland",
    "Russia": "Russia",
    "Ukraine": "Ukraine",
    "Czech": "Czech",
    "Slovakia": "Slovakia",
    "Hungary": "Hungary",
    "Croatia": "Croatia",
    "Serbia": "Serbia",
    "Slovenia": "Slovenia",
    "Bulgaria": "Bulgaria",
    "Romania": "Romania",
    "Estonia": "Estonia",
    "Latvia": "Latvia",
    "Lithuania": "Lithuania",
    "Turkey": "Turkey",
    "Israel": "Israel",
    "UAE": "UAE",
    "India": "India",
    "South Africa": "South Africa",
    "Canada": "Canada",
    "Mexico": "Mexico",
    "Argentina": "Argentina",
    "Latin America": "Latin America",
    "New Zealand": "New Zealand",
    "Singapore": "Singapore",
    "Thailand": "Thailand",
    "Unknown": "Unknown",
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
    "Da": "Danish",
    "Danish": "Danish",
    "No": "Norwegian",
    "Nn": "Norwegian",
    "Norwegian": "Norwegian",
    "Fi": "Finnish",
    "Finnish": "Finnish",
    "Pl": "Polish",
    "Polish": "Polish",
    "Ru": "Russian",
    "Russian": "Russian",
    "Uk": "Ukrainian",
    "Ko": "Korean",
    "Korean": "Korean",
    "Zh": "Chinese",
    "Chinese": "Chinese",
    "Cs": "Czech",
    "Sk": "Slovak",
    "Hu": "Hungarian",
    "El": "Greek",
    "Tr": "Turkish",
    "He": "Hebrew",
    "Ar": "Arabic",
    "Hi": "Hindi",
    "Th": "Thai",
    "Vi": "Vietnamese",
    "Id": "Indonesian",
    "Hr": "Croatian",
    "Sr": "Serbian",
    "Sl": "Slovenian",
    "Bg": "Bulgarian",
    "Ro": "Romanian",
    "Et": "Estonian",
    "Lv": "Latvian",
    "Lt": "Lithuanian",
    # Idiomas cooficiales de España: un usuario con prioridad "Spanish" no debe
    # perder la edición catalana o gallega por no reconocerse el código.
    "Ca": "Catalan",
    "Catalan": "Catalan",
    "Gl": "Galician",
    "Eu": "Basque",
    "Multi": "Multi",
    "Multilanguage": "Multi",
}

# "Multi5", "Multi 3", "M5": todas quieren decir lo mismo y ninguna casaba con
# la clave exacta "Multi", así que una ROM multiidioma salía sin idioma.
_MULTI_PATTERN = re.compile(r"^(?:multi|m)\s*[0-9]+$", re.I)

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


# Una sola expresión con todas las etiquetas, para descartar de un tiro los
# nombres que no llevan ninguna. Las más largas van primero porque unas
# contienen a otras ("Nintendo Switch Online" y "Switch Online").
_ANY_TAG = re.compile(r"\b(?:" + "|".join(re.escape(keyword) for keyword in sorted(TAG_KEYWORDS, key=len, reverse=True)) + r")\b", re.I)


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
        group_languages: set[str] = set()
        for part_text in parts:
            part_text = re.sub(r"\s+", " ", part_text).strip()
            if part is None:
                part = detect_part(part_text)
            normalized = REGION_ALIASES.get(part_text)
            if normalized and normalized not in regions:
                regions.append(normalized)
            language = "Multi" if _MULTI_PATTERN.match(part_text) else LANGUAGE_ALIASES.get(part_text)
            if language:
                group_languages.add(language)
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
            # El filtro previo evita las 28 búsquedas cuando no hay ninguna
            # etiqueta, que es el caso de la inmensa mayoría de los nombres:
            # cargar un DAT grande se iba en compilar esas expresiones una y
            # otra vez. Cuando sí hay, se recorren todas como antes, porque un
            # nombre puede llevar varias y unas contienen a otras.
            if _ANY_TAG.search(part_text):
                for keyword in TAG_KEYWORDS:
                    if keyword not in tags and re.search(rf"\b{re.escape(keyword)}\b", part_text, re.I):
                        tags.append(keyword)
        # Dos idiomas o más en el mismo grupo son una edición multiidioma:
        # "(En,Fr,De)" es Multi aunque el nombre no lo diga. Se cuentan los
        # idiomas ya reconocidos en vez de una lista de códigos aparte, que se
        # quedaba corta en cuanto se añadía uno nuevo.
        if len(group_languages - {"Multi"}) >= 2 and "Multi" not in languages:
            languages.append("Multi")

    return DetectedMetadata(title=title or stem, regions=regions, languages=languages, version=version, revision=revision, tags=tags, part=part)
