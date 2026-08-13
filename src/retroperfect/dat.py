from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
import re
import binascii
import hashlib

from .metadata import parse_no_intro_name
from .models import DatCatalog, DatGame, DatRom


def _text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    return node.text.strip()


def parse_logiqx_dat(path: Path) -> DatCatalog:
    tree = ET.parse(path)
    root = tree.getroot()
    header = root.find("header")
    catalog = DatCatalog(
        name=_text(header.find("name")) if header is not None else None,
        description=_text(header.find("description")) if header is not None else None,
    )

    for game_node in [*root.findall("game"), *root.findall("machine")]:
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
        catalog.games.append(game)
    _resolve_cloneof_ids(catalog)
    return catalog


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
        self.by_md5: dict[str, DatGame] = {}
        self.by_sha1: dict[str, DatGame] = {}
        self.by_size: dict[int, list[DatGame]] = {}
        self.by_set_name: dict[str, DatGame] = {}
        self.headered_candidates_by_payload_size: dict[int, list[bytes]] = {}
        self.headered_candidates_by_name: dict[str, list[tuple[DatGame, bytes]]] = {}
        for game in catalog.games:
            if game.name:
                self.by_set_name[_name_key(game.name)] = game
            if game.description:
                self.by_set_name.setdefault(_name_key(game.description), game)
            for rom in game.roms:
                if rom.crc32:
                    self.by_crc.setdefault(rom.crc32, []).append((game, rom.size))
                if rom.md5:
                    self.by_md5[rom.md5] = game
                if rom.sha1:
                    self.by_sha1[rom.sha1] = game
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
        game = self.by_sha1.get(sha1.lower()) or self.by_md5.get(md5.lower())
        if game:
            return game
        for candidate, rom_size in self.by_crc.get(crc32.lower(), []):
            if rom_size is None or rom_size == size:
                return candidate
        return None

    def match_any(self, hashes) -> DatGame | None:
        full = self.match(hashes.crc32, hashes.md5, hashes.sha1, hashes.size)
        if full:
            return full
        if hashes.payload_crc32 and hashes.payload_md5 and hashes.payload_sha1 and hashes.payload_size:
            return self.match(hashes.payload_crc32, hashes.payload_md5, hashes.payload_sha1, hashes.payload_size)
        return None

    def match_data(self, data: bytes, hashes, filename: str | None = None) -> DatGame | None:
        direct = self.match_any(hashes)
        if direct:
            return direct
        if filename:
            for game, header in self.headered_candidates_by_name.get(_name_key(filename), []):
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

    def _match_headered_payload(self, data: bytes, header: bytes) -> DatGame | None:
        candidate = header + data
        return self.match(
            f"{binascii.crc32(candidate) & 0xFFFFFFFF:08x}",
            hashlib.md5(candidate).hexdigest(),
            hashlib.sha1(candidate).hexdigest(),
            len(candidate),
        )


def _infer_releases(game: DatGame) -> None:
    candidates = [game.description or game.name, game.name, *[rom.name for rom in game.roms]]
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
