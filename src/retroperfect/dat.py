from __future__ import annotations

import binascii
import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .metadata import parse_no_intro_name
from .models import DatCatalog, DatGame, DatRom


def _text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    return node.text.strip()


def parse_logiqx_dat(path: Path) -> DatCatalog:
    """Lee un DAT XML (Logiqx/MAME) sin construir el árbol completo en memoria.

    Los DAT de MAME pasan de 200 MB de XML y el árbol de ElementTree ocupa
    varias veces eso; con `iterparse` se procesa juego a juego y se sueltan los
    nodos ya leídos. Los juegos salen en el orden del archivo (antes se leían
    primero todos los `game` y luego todos los `machine`, pero ningún DAT mezcla
    ambas etiquetas).
    """
    _reject_internal_dtd(path)
    catalog = DatCatalog()
    context = ET.iterparse(path, events=("start", "end"))
    _event, root = next(context)
    for event, node in context:
        if event != "end":
            continue
        if node.tag == "header":
            catalog.name = _text(node.find("name"))
            catalog.description = _text(node.find("description"))
            node.clear()
        elif node.tag in {"game", "machine"}:
            catalog.games.append(_game_from_node(node))
            node.clear()
            # El raíz acumula los hijos ya procesados: sin esto, iterparse
            # gasta tanta memoria como ET.parse.
            root.clear()
    _resolve_cloneof_ids(catalog)
    return catalog


def _game_from_node(game_node: ET.Element) -> DatGame:
    game = DatGame(
        name=game_node.attrib.get("name", ""),
        dat_id=game_node.attrib.get("id") or None,
        cloneof=game_node.attrib.get("cloneof") or None,
        description=_text(game_node.find("description")),
    )
    cloneofid = game_node.attrib.get("cloneofid")
    if cloneofid and not game.cloneof:
        game.cloneof = cloneofid
    for release in game_node.findall("release"):
        region = release.attrib.get("region")
        if region and region not in game.releases:
            game.releases.append(region)
    for rom_node in game_node.findall("rom"):
        size_raw = rom_node.attrib.get("size")
        game.roms.append(
            DatRom(
                name=rom_node.attrib.get("name", ""),
                size=int(size_raw) if size_raw and size_raw.isdigit() else None,
                crc32=(rom_node.attrib.get("crc") or "").lower() or None,
                md5=(rom_node.attrib.get("md5") or "").lower() or None,
                sha1=(rom_node.attrib.get("sha1") or "").lower() or None,
                header=rom_node.attrib.get("header") or None,
            )
        )
    _infer_releases(game)
    return game


# Bytes del prólogo que se revisan buscando declaraciones de entidades.
PROLOGUE_BYTES = 64 * 1024
_INTERNAL_DTD = re.compile(rb"<!DOCTYPE[^>\[]*\[|<!ENTITY", re.I)


def _reject_internal_dtd(path: Path) -> None:
    """Rechaza un DAT que declare entidades XML propias.

    El DOCTYPE que traen los DAT de No-Intro apunta al DTD de Logiqx y es
    inofensivo: ElementTree no va a buscarlo. Lo peligroso es el subconjunto
    interno (`<!DOCTYPE ... [ <!ENTITY ...> ]>`), con el que se escribe un XML
    diminuto que al expandirse agota la memoria. Ningún DAT legítimo lo
    necesita y estos archivos se descargan de espejos públicos.
    """
    with path.open("rb") as fh:
        prologue = fh.read(PROLOGUE_BYTES)
    if _INTERNAL_DTD.search(prologue):
        raise ValueError(f"El DAT {path.name} declara entidades XML propias; RetroPerfect no las procesa por seguridad.")


def parse_clrmamepro_dat(path: Path) -> DatCatalog:
    text = path.read_text(encoding="utf-8", errors="replace")
    catalog = DatCatalog()
    header_match = re.search(r"clrmamepro\s*\((.*?)\)\s*", text, re.S | re.I)
    if header_match:
        catalog.name = _clrmame_value(header_match.group(1), "name")
        catalog.description = _clrmame_value(header_match.group(1), "description")

    for body in _blocks(text, "game"):
        name = _clrmame_value(body, "name") or ""
        cloneof = _clrmame_value(body, "cloneof")
        region = _clrmame_value(body, "region")
        game = DatGame(name=name, description=name, cloneof=cloneof)
        if region:
            game.releases.append(region)
        for rom_body in _blocks(body, "rom"):
            size_raw = _clrmame_token(rom_body, "size")
            game.roms.append(
                DatRom(
                    name=_clrmame_value(rom_body, "name") or "",
                    size=int(size_raw) if size_raw and size_raw.isdigit() else None,
                    crc32=(_clrmame_token(rom_body, "crc") or "").lower() or None,
                    md5=(_clrmame_token(rom_body, "md5") or "").lower() or None,
                    sha1=(_clrmame_token(rom_body, "sha1") or "").lower() or None,
                    header=_clrmame_value(rom_body, "header"),
                )
            )
        _infer_releases(game)
        catalog.games.append(game)
    return catalog


def parse_dat(path: Path) -> DatCatalog:
    with path.open(encoding="utf-8", errors="replace") as fh:
        prefix = fh.read(256).lstrip()
    if prefix.startswith("<") or prefix.startswith("<?xml"):
        return parse_logiqx_dat(path)
    return parse_clrmamepro_dat(path)


def _clrmame_value(body: str, key: str) -> str | None:
    quoted = re.search(rf"\b{re.escape(key)}\s+\"([^\"]*)\"", body, re.I)
    if quoted:
        return quoted.group(1)
    return _clrmame_token(body, key)


def _clrmame_token(body: str, key: str) -> str | None:
    match = re.search(rf"\b{re.escape(key)}\s+([^\s\)]+)", body, re.I)
    return match.group(1) if match else None


def _blocks(text: str, name: str) -> list[str]:
    blocks: list[str] = []
    searchable = _mask_quoted(text)
    pattern = re.compile(rf"\b{re.escape(name)}\s*\(", re.I)
    for match in pattern.finditer(searchable):
        index = match.end()
        depth = 1
        while index < len(searchable) and depth:
            if searchable[index] == "(":
                depth += 1
            elif searchable[index] == ")":
                depth -= 1
            index += 1
        if depth == 0:
            blocks.append(text[match.end() : index - 1])
    return blocks


def _mask_quoted(text: str) -> str:
    chars = list(text)
    in_quote = False
    escaped = False
    for index, char in enumerate(chars):
        if escaped:
            escaped = False
            if in_quote:
                chars[index] = " "
            continue
        if char == "\\":
            escaped = True
            if in_quote:
                chars[index] = " "
            continue
        if char == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            chars[index] = " "
    return "".join(chars)


class DatIndex:
    def __init__(self, catalog: DatCatalog):
        self.catalog = catalog
        self.by_crc: dict[str, list[tuple[DatGame, int | None]]] = {}
        # Listas, no un juego por hash: dos entradas del DAT pueden declarar
        # la misma ROM (clones de MAME, dumps idénticos de dos regiones) y
        # guardar solo una hacía que ganara la ÚLTIMA del archivo, así que el
        # juego con el que casaba un archivo dependía del orden del DAT. Ahora
        # gana la primera, que en los DAT con parent/clone es la de referencia.
        self.by_md5: dict[str, list[DatGame]] = {}
        self.by_sha1: dict[str, list[DatGame]] = {}
        self.by_size: dict[int, list[DatGame]] = {}
        self.by_set_name: dict[str, DatGame] = {}
        self.by_track_sha1s: dict[tuple[str, ...], DatGame] = {}
        self.headered_candidates_by_payload_size: dict[int, list[bytes]] = {}
        self.headered_candidates_by_name: dict[str, list[tuple[DatGame, bytes]]] = {}
        for game in catalog.games:
            if game.name:
                self.by_set_name[_name_key(game.name)] = game
            if game.description:
                self.by_set_name.setdefault(_name_key(game.description), game)
            # Un CHD contiene las pistas pero no el .cue/.gdi (texto de layout),
            # así que la clave son los sha1 de las pistas, sin orden.
            track_sha1s = sorted(rom.sha1 for rom in game.roms if rom.sha1 and not rom.name.lower().endswith((".cue", ".gdi")))
            if track_sha1s:
                self.by_track_sha1s.setdefault(tuple(track_sha1s), game)
            for rom in game.roms:
                if rom.crc32:
                    self.by_crc.setdefault(rom.crc32, []).append((game, rom.size))
                if rom.md5:
                    self.by_md5.setdefault(rom.md5, []).append(game)
                if rom.sha1:
                    self.by_sha1.setdefault(rom.sha1, []).append(game)
                if rom.size is not None:
                    self.by_size.setdefault(rom.size, []).append(game)
                header = _header_bytes(rom.header)
                if header and rom.size is not None and rom.size > len(header):
                    payload_size = rom.size - len(header)
                    headers = self.headered_candidates_by_payload_size.setdefault(payload_size, [])
                    if header not in headers:
                        headers.append(header)
                    self.headered_candidates_by_name.setdefault(_name_key(rom.name), []).append((game, header))

    def match(self, crc32: str, md5: str, sha1: str, size: int) -> DatGame | None:
        for games in (self.by_sha1.get(sha1.lower()), self.by_md5.get(md5.lower())):
            if games:
                return games[0]
        for candidate, rom_size in self.by_crc.get(crc32.lower(), []):
            if rom_size is None or rom_size == size:
                return candidate
        return None

    def match_any(self, hashes) -> DatGame | None:
        full = self.match(hashes.crc32, hashes.md5, hashes.sha1, hashes.size)
        if full:
            return full
        if hashes.payload_crc32 and hashes.payload_md5 and hashes.payload_sha1 and hashes.payload_size:
            payload = self.match(hashes.payload_crc32, hashes.payload_md5, hashes.payload_sha1, hashes.payload_size)
            if payload:
                return payload
        if hashes.track_sha1s:
            return self.by_track_sha1s.get(tuple(sorted(sha1.lower() for sha1 in hashes.track_sha1s)))
        return None

    def match_data(self, data: bytes, hashes, filename: str | None = None) -> DatGame | None:
        direct = self.match_any(hashes)
        if direct:
            return direct
        if filename:
            for _game, header in self.headered_candidates_by_name.get(_name_key(filename), []):
                match = self._match_headered_payload(data, header)
                if match:
                    return match
        headers = self.headered_candidates_by_payload_size.get(len(data), [])
        for header in headers:
            match = self._match_headered_payload(data, header)
            if match:
                return match
        return None

    def match_set(self, set_name: str) -> DatGame | None:
        return self.by_set_name.get(_name_key(set_name))

    @property
    def has_header_candidates(self) -> bool:
        return bool(self.headered_candidates_by_payload_size or self.headered_candidates_by_name)

    def _match_headered_payload(self, data: bytes, header: bytes) -> DatGame | None:
        candidate = header + data
        return self.match(
            f"{binascii.crc32(candidate) & 0xFFFFFFFF:08x}",
            hashlib.md5(candidate).hexdigest(),
            hashlib.sha1(candidate).hexdigest(),
            len(candidate),
        )


def dat_rom_for_hashes(game: DatGame, hashes) -> DatRom | None:
    """Entrada del DAT que corresponde a un archivo concreto del juego.

    Un juego puede declarar varias ROMs (un .cue y sus .bin), así que dar por
    hecho que es la primera hace que se acuse de mal nombrado a todo lo demás,
    con el consejo de renombrarlas todas igual."""
    candidates = [(hashes.sha1, hashes.md5, hashes.crc32, hashes.size)]
    if hashes.payload_sha1:
        candidates.append((hashes.payload_sha1, hashes.payload_md5, hashes.payload_crc32, hashes.payload_size))
    for sha1, md5, crc32, size in candidates:
        for rom in game.roms:
            if (rom.sha1 and rom.sha1 == (sha1 or "").lower()) or (rom.md5 and rom.md5 == (md5 or "").lower()):
                return rom
            if rom.crc32 and rom.crc32 == (crc32 or "").lower() and (rom.size is None or rom.size == size):
                return rom
    return game.roms[0] if game.roms else None


def _infer_releases(game: DatGame) -> None:
    # Sin repetidos: en la mayoría de los DAT la descripción es igual que el
    # nombre, y el de la ROM solo añade la extensión, así que se parseaba tres
    # veces lo mismo por juego.
    candidates = dict.fromkeys([game.description or game.name, game.name, *[rom.name for rom in game.roms]])
    for candidate in candidates:
        metadata = parse_no_intro_name(candidate)
        for region in metadata.regions:
            if region not in game.releases:
                game.releases.append(region)


def _resolve_cloneof_ids(catalog: DatCatalog) -> None:
    by_id = {game.dat_id: game for game in catalog.games if game.dat_id}
    for game in catalog.games:
        if game.cloneof in by_id:
            game.cloneof = by_id[game.cloneof].name


def _header_bytes(header: str | None) -> bytes | None:
    if not header:
        return None
    try:
        return bytes.fromhex(header)
    except ValueError:
        return None


def _name_key(name: str) -> str:
    return Path(name).stem.casefold()
