"""Comparar dos escaneos: qué ha cambiado en la colección.

Los escaneos se guardan con retención, así que la información para responder
"¿qué ha cambiado desde el mes pasado?" ya estaba en disco y no había forma de
preguntarlo.

Lo que de verdad importa aquí no son las altas y las bajas —esas se ven mirando
la carpeta—, sino los archivos **cuyo hash cambió sin cambiar de nombre**. Eso
es un archivo corrompido en disco, una descarga que sobrescribió otra o un
parche aplicado por error, y es justo lo que nadie nota: el archivo sigue ahí y
con el mismo nombre.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .models import ScannedRom, ScanResult


class DiffEntry(BaseModel):
    kind: str
    path: str
    detail: str = ""

    @property
    def name(self) -> str:
        return Path(self.path).name


KIND_LABELS = {
    "añadido": "Añadido",
    "eliminado": "Eliminado",
    "cambiado": "Cambió su contenido",
    "movido": "Movido o renombrado",
}


class ScanDiff(BaseModel):
    before_id: str
    after_id: str
    added: list[DiffEntry] = Field(default_factory=list)
    removed: list[DiffEntry] = Field(default_factory=list)
    changed: list[DiffEntry] = Field(default_factory=list)
    moved: list[DiffEntry] = Field(default_factory=list)
    unchanged: int = 0
    matched_before: int = 0
    matched_after: int = 0

    @property
    def identical(self) -> bool:
        return not (self.added or self.removed or self.changed or self.moved)

    @property
    def entries(self) -> list[DiffEntry]:
        """Todas las diferencias, con lo preocupante primero."""
        return [*self.changed, *self.removed, *self.added, *self.moved]


def _key(rom: ScannedRom) -> str:
    return f"{rom.container_path}|{rom.inner_path}" if rom.inner_path else rom.container_path


def _label(rom: ScannedRom) -> str:
    if rom.inner_path:
        return f"{Path(rom.container_path).name} / {rom.inner_path}"
    return Path(rom.container_path).name


def diff_scans(before: ScanResult, after: ScanResult) -> ScanDiff:
    """Compara dos escaneos de la misma colección.

    Un archivo se identifica por su ruta; el contenido, por su MD5. Cruzando las
    dos cosas se distingue un archivo nuevo de uno que solo ha cambiado de
    nombre, y un borrado de un movimiento.
    """
    antes = {_key(rom): rom for rom in before.roms}
    despues = {_key(rom): rom for rom in after.roms}
    hashes_antes: dict[str, list[ScannedRom]] = {}
    for rom in before.roms:
        hashes_antes.setdefault(rom.hashes.md5, []).append(rom)
    hashes_despues = {rom.hashes.md5 for rom in after.roms}

    diff = ScanDiff(
        before_id=before.id,
        after_id=after.id,
        matched_before=sum(1 for rom in before.roms if rom.dat_game is not None),
        matched_after=sum(1 for rom in after.roms if rom.dat_game is not None),
    )

    for clave, rom in sorted(despues.items()):
        anterior = antes.get(clave)
        if anterior is None:
            origen = [item for item in hashes_antes.get(rom.hashes.md5, []) if _key(item) not in despues]
            if origen:
                diff.moved.append(DiffEntry(kind="movido", path=_key(rom), detail=f"antes estaba en {_label(origen[0])}"))
            else:
                diff.added.append(DiffEntry(kind="añadido", path=_key(rom), detail=_dat_detail(rom)))
        elif anterior.hashes.md5 != rom.hashes.md5:
            diff.changed.append(
                DiffEntry(
                    kind="cambiado",
                    path=_key(rom),
                    # Los MD5 recortados caben en la tabla y bastan para
                    # distinguirlos; el escaneo guarda los completos.
                    detail=f"MD5 {anterior.hashes.md5[:12]} → {rom.hashes.md5[:12]}; {_size_detail(anterior, rom)}",
                )
            )
        else:
            diff.unchanged += 1

    for clave, rom in sorted(antes.items()):
        if clave in despues:
            continue
        if rom.hashes.md5 in hashes_despues:
            continue  # aparece en otro sitio: ya se contó como movido
        diff.removed.append(DiffEntry(kind="eliminado", path=clave, detail=_dat_detail(rom)))

    return diff


def _dat_detail(rom: ScannedRom) -> str:
    return f"DAT: {rom.dat_game.name}" if rom.dat_game else "sin coincidencia en el DAT"


def _size_detail(antes: ScannedRom, despues: ScannedRom) -> str:
    if antes.hashes.size == despues.hashes.size:
        return "mismo tamaño, así que no es un truncamiento"
    return f"{antes.hashes.size} → {despues.hashes.size} bytes"
