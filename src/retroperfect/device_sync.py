"""Llenar un dispositivo con lo mejor de la colección, sin pasarse del tamaño.

"Llena esta SD de 32 GB con lo mejor que tengo" es lo que se quiere hacer con
una consola portátil, una Steam Deck o la tarjeta de una máquina recreativa, y
hasta ahora había que ir copiando a ojo.

No es un comando aparte: es **un plan acotado**. Se construye el mismo
manifiesto que cura la colección, con el dispositivo como salida, y se le quitan
los juegos que no caben. Así hereda todo lo que ya estaba resuelto —1G1R con
motivos explicables, carpetas por región, playlists de varios discos, ZIP por
juego, verificación por MD5, omitir lo que ya está, deshacer— y lo único nuevo
aquí es decidir qué entra.

La unidad es el **juego entero**, no el archivo: un juego de tres discos entra
con los tres o no entra. Medio juego ocupa sitio y no se puede terminar, que es
el mismo razonamiento por el que los discos no compiten entre sí en el 1G1R.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .manifest_io import bytes_to_write
from .models import Manifest, ScanResult

# Cómo se decide el orden en el que entran los juegos. Las claves son parte de
# la interfaz de línea de comandos, así que no se traducen; las descripciones
# sí, y por eso van en una función (ver `i18n.py`).
SYNC_ORDERS = {
    "size": "Los más pequeños primero: caben más juegos",
    "name": "Por título, alfabéticamente",
    "ra": "Primero los que tienen logros de RetroAchievements, luego los pequeños",
}


def sync_order_labels() -> dict[str, str]:
    from .i18n import _

    return {clave: _(texto) for clave, texto in SYNC_ORDERS.items()}


class SyncGame(BaseModel):
    """Un juego con todo lo que ocupa en el dispositivo."""

    title: str
    size: int
    files: int
    ra: bool = False
    rom_ids: list[str] = Field(default_factory=list)


class SyncReport(BaseModel):
    destination: str
    budget: int
    order: str
    included: list[SyncGame] = Field(default_factory=list)
    excluded: list[SyncGame] = Field(default_factory=list)

    @property
    def bytes_planned(self) -> int:
        return sum(game.size for game in self.included)

    @property
    def bytes_left(self) -> int:
        return max(0, self.budget - self.bytes_planned)

    @property
    def ra_included(self) -> int:
        return sum(1 for game in self.included if game.ra)


def parse_budget(value: str) -> int:
    """Convierte "32GB", "512 MiB" o "1500000000" en bytes.

    Se admiten las dos convenciones porque las tarjetas se venden en GB
    decimales y los sistemas las miden en GiB: dar por supuesta una de las dos
    es la forma de prometer un hueco que no existe.
    """
    texto = value.strip().replace(" ", "").upper()
    # Los sufijos binarios van primero: "GIB" acaba en "B" igual que "GB", así
    # que el orden de comprobación decide cuál gana.
    unidades = [("KIB", 1024), ("MIB", 1024**2), ("GIB", 1024**3), ("TIB", 1024**4), ("KB", 1000), ("MB", 1000**2), ("GB", 1000**3), ("TB", 1000**4)]
    numero, factor = texto, 1
    for sufijo, multiplicador in unidades:
        if texto.endswith(sufijo):
            numero, factor = texto[: -len(sufijo)], multiplicador
            break
    try:
        cantidad = float(numero)
    except ValueError as exc:
        raise ValueError(f"Tamaño no entendido: {value!r}. Usa algo como 32GB, 512MiB o el número de bytes.") from exc
    if cantidad <= 0:
        raise ValueError(f"El tamaño tiene que ser positivo: {value!r}")
    return int(cantidad * factor)


def plan_device_sync(manifest: Manifest, scan: ScanResult, destination: Path, budget: int, order: str = "size") -> tuple[Manifest, SyncReport]:
    """Recorta el manifiesto a lo que cabe y devuelve (plan, informe).

    Un juego que no cabe se salta y se sigue con el siguiente: si uno grande
    cortara la lista, un solo juego de 8 GB dejaría la tarjeta medio vacía.
    """
    if order not in SYNC_ORDERS:
        raise ValueError(f"Orden desconocido: {order!r}. Usa uno de: {', '.join(SYNC_ORDERS)}.")
    juegos = _games(manifest, scan)
    report = SyncReport(destination=str(destination), budget=budget, order=order)
    ocupado = 0
    elegidos: set[str] = set()
    for juego in sorted(juegos, key=_sort_key(order)):
        if ocupado + juego.size <= budget:
            report.included.append(juego)
            elegidos.update(juego.rom_ids)
            ocupado += juego.size
        else:
            report.excluded.append(juego)
    return _trim(manifest, elegidos), report


def _games(manifest: Manifest, scan: ScanResult) -> list[SyncGame]:
    """Agrupa las entradas del plan por juego, con lo que ocupa cada uno."""
    rom_by_id = {rom.id: rom for rom in scan.roms}
    acumulado: dict[str, SyncGame] = {}
    contados: set[tuple[str, str]] = set()
    for entry in manifest.entries:
        if not entry.destination_path:
            continue
        rom = rom_by_id.get(entry.rom_id)
        # El título sin el soporte: los discos de un juego son el mismo juego.
        titulo = rom.metadata.title if rom else Path(entry.destination_path).stem
        juego = acumulado.setdefault(titulo, SyncGame(title=titulo, size=0, files=0))
        # Una misma ROM puede aparecer en main y en ra: ocupa una vez.
        clave = (titulo, entry.destination_path)
        if clave in contados:
            continue
        contados.add(clave)
        juego.size += bytes_to_write(entry, Path(entry.source_path))
        juego.files += 1
        juego.ra = juego.ra or bool(entry.ra_game_id)
        juego.rom_ids.append(entry.rom_id)
    return list(acumulado.values())


def _sort_key(order: str):
    if order == "name":
        return lambda juego: juego.title.lower()
    if order == "ra":
        return lambda juego: (0 if juego.ra else 1, juego.size, juego.title.lower())
    return lambda juego: (juego.size, juego.title.lower())


def _trim(manifest: Manifest, elegidos: set[str]) -> Manifest:
    """Manifiesto con solo los juegos elegidos, playlists y ZIP incluidos."""
    recortado = manifest.model_copy(deep=True)
    recortado.entries = [entry for entry in recortado.entries if entry.rom_id in elegidos]
    destinos = {entry.destination_path for entry in recortado.entries if entry.destination_path}
    # Un .m3u o un ZIP cuyo juego no entra no tiene nada que listar.
    recortado.archives = [archive for archive in recortado.archives if archive.path in destinos]
    carpetas = {str(Path(destino).parent) for destino in destinos}
    nombres = {Path(destino).name for destino in destinos}
    recortado.playlists = [
        playlist
        for playlist in recortado.playlists
        if str(Path(playlist.path).parent) in carpetas and all(entrada in nombres for entrada in playlist.entries)
    ]
    return recortado
