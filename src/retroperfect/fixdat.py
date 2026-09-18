"""Fixdat: un DAT con solo lo que te falta.

Es el formato de intercambio del mundillo: se lo pasas a otra herramienta, a un
tracker o a un amigo y te completa el set. RetroPerfect dice *qué* falta sin
distribuir nada, que es justo su postura.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from .models import DatCatalog, DatGame, DatRom, Platform, ScanResult
from .platforms import platform_spec


def missing_roms(catalog: DatCatalog, scan: ScanResult | None) -> list[tuple[DatGame, list[DatRom]]]:
    """Juegos del DAT con las ROMs que no aparecen en el escaneo.

    Un juego puede estar a medias (te falta una pista de las tres), así que se
    listan las ROMs que faltan, no solo los juegos ausentes por completo.
    """
    presentes: set[str] = set()
    for rom in (scan.roms if scan else []):
        for valor in (rom.hashes.sha1, rom.hashes.md5, rom.hashes.crc32, rom.hashes.payload_sha1, rom.hashes.payload_md5, rom.hashes.payload_crc32):
            if valor:
                presentes.add(valor.lower())

    faltan: list[tuple[DatGame, list[DatRom]]] = []
    for game in catalog.games:
        ausentes = [rom for rom in game.roms if not _presente(rom, presentes)]
        if ausentes:
            faltan.append((game, ausentes))
    return faltan


def _presente(rom: DatRom, presentes: set[str]) -> bool:
    return any(valor and valor.lower() in presentes for valor in (rom.sha1, rom.md5, rom.crc32))


def build_fixdat(catalog: DatCatalog, scan: ScanResult | None, platform: Platform) -> str:
    """XML Logiqx con lo que falta, listo para dárselo a otra herramienta."""
    spec = platform_spec(platform)
    nombre = catalog.name or spec.dat_aliases[0]
    raiz = ET.Element("datafile")
    cabecera = ET.SubElement(raiz, "header")
    ET.SubElement(cabecera, "name").text = f"{nombre} (fixdat)"
    ET.SubElement(cabecera, "description").text = f"Lo que falta de {nombre} según RetroPerfect"
    ET.SubElement(cabecera, "version").text = datetime.now(UTC).strftime("%Y-%m-%d")
    ET.SubElement(cabecera, "author").text = "RetroPerfect"

    for game, roms in missing_roms(catalog, scan):
        nodo = ET.SubElement(raiz, "game", {"name": game.name})
        if game.cloneof:
            nodo.set("cloneof", game.cloneof)
        ET.SubElement(nodo, "description").text = game.description or game.name
        for rom in roms:
            atributos = {"name": rom.name}
            if rom.size is not None:
                atributos["size"] = str(rom.size)
            for clave, valor in (("crc", rom.crc32), ("md5", rom.md5), ("sha1", rom.sha1)):
                if valor:
                    atributos[clave] = valor
            ET.SubElement(nodo, "rom", atributos)

    ET.indent(raiz, space="  ")
    return '<?xml version="1.0"?>\n' + ET.tostring(raiz, encoding="unicode") + "\n"
