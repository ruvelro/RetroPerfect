"""Renombrar en el sitio los archivos que no se llaman como dice el DAT.

`verify` ya detectaba los mal nombrados y no había forma de arreglarlos: había
que planificar una copia entera de la colección para conseguir los nombres
buenos. Esto los corrige donde están, sin mover nada.

El nombre correcto sale de la entrada del DAT que casa con el hash del archivo
(`dat_rom_for_hashes`), no de la primera ROM del juego: un juego de Redump son
varias pistas y cada una tiene su nombre.

Dos cosas que parecen detalles y no lo son:

- **Las extensiones no se tocan.** El DAT de Redump llama a una pista
  `Juego (Europe) (Track 1).bin`, pero el archivo puede ser un `.chd` que
  contiene todas las pistas, o una ROM con cabecera donde el DAT indexa el
  payload. Renombrar `.chd` a `.bin` rompería el romset, así que se conserva la
  extensión que ya tiene el archivo y solo se cambia el nombre.
- **Nada se sobrescribe.** Si el nombre de destino ya existe, se omite y se
  dice; si dos archivos quieren el mismo nombre, se omiten los dos.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .dat import dat_rom_for_hashes
from .models import ScannedRom, ScanResult


class RenamePlan(BaseModel):
    """Un renombrado previsto, o el motivo por el que no se puede hacer."""

    source_path: str
    current_name: str
    expected_name: str
    inner_path: str | None = None
    skipped_reason: str = ""

    @property
    def can_apply(self) -> bool:
        return not self.skipped_reason

    @property
    def destination_path(self) -> str:
        return str(Path(self.source_path).parent / self.expected_name)


def expected_file_name(rom: ScannedRom) -> str | None:
    """Nombre que el DAT le da a este archivo, conservando su extensión actual."""
    if not rom.dat_game or not rom.dat_game.roms:
        return None
    matched = dat_rom_for_hashes(rom.dat_game, rom.hashes)
    if matched is None or not matched.name:
        return None
    actual = Path(rom.inner_path or rom.container_path)
    return Path(matched.name).stem + actual.suffix


def current_file_name(rom: ScannedRom) -> str:
    return Path(rom.inner_path or rom.container_path).name


def plan_renames(scan: ScanResult) -> list[RenamePlan]:
    """Qué habría que renombrar y qué no se puede, en el orden del escaneo."""
    plans: list[RenamePlan] = []
    for rom in scan.roms:
        expected = expected_file_name(rom)
        if expected is None:
            continue
        current = current_file_name(rom)
        if current == expected:
            continue
        plan = RenamePlan(
            source_path=rom.container_path,
            current_name=current,
            expected_name=expected,
            inner_path=rom.inner_path,
        )
        if rom.inner_path:
            # Cambiar el nombre de una entrada comprimida obliga a reescribir el
            # contenedor entero, que es otra función (y otro riesgo).
            plan.skipped_reason = f"Está dentro de {Path(rom.container_path).name}: haría falta reempaquetar el contenedor."
        plans.append(plan)
    return _mark_conflicts(plans)


def _mark_conflicts(plans: list[RenamePlan]) -> list[RenamePlan]:
    """Marca los destinos que chocan entre sí o con un archivo que ya existe."""
    wanted: dict[str, list[RenamePlan]] = {}
    for plan in plans:
        if plan.can_apply:
            wanted.setdefault(plan.destination_path.casefold(), []).append(plan)
    for destination, competing in wanted.items():
        if len(competing) > 1:
            nombres = ", ".join(sorted(plan.current_name for plan in competing))
            for plan in competing:
                plan.skipped_reason = f"Varios archivos quieren el mismo nombre ({nombres}): revísalos a mano."
            continue
        plan = competing[0]
        objetivo = Path(plan.destination_path)
        # Un renombrado que solo cambia mayúsculas no es una colisión: en macOS
        # y Windows el propio archivo "ya existe" con el nombre nuevo.
        if objetivo.exists() and destination != Path(plan.source_path).as_posix().casefold():
            plan.skipped_reason = f"Ya existe un archivo llamado {plan.expected_name}: no se sobrescribe."
    return plans


def apply_renames(plans: list[RenamePlan]) -> list[str]:
    """Renombra lo que se puede y devuelve el registro de lo hecho y lo omitido."""
    log: list[str] = []
    for plan in plans:
        if not plan.can_apply:
            log.append(f"omitido {plan.current_name}: {plan.skipped_reason}")
            continue
        origen = Path(plan.source_path)
        destino = Path(plan.destination_path)
        if not origen.exists():
            log.append(f"omitido {plan.current_name}: el archivo ya no está en {origen.parent}.")
            continue
        try:
            _rename(origen, destino)
        except OSError as exc:
            log.append(f"error al renombrar {plan.current_name}: {exc}")
            continue
        log.append(f"renombrado {plan.current_name} -> {plan.expected_name}")
    return log


def _rename(origen: Path, destino: Path) -> None:
    """Renombra, con el rodeo que hace falta si solo cambian las mayúsculas.

    En macOS y Windows el sistema de archivos no distingue mayúsculas, así que
    `Juego.nes` -> `juego.nes` es un renombrado sobre sí mismo que algunos
    sistemas ignoran. Pasar por un nombre intermedio lo hace efectivo.
    """
    if origen == destino:
        return
    if origen.name.casefold() == destino.name.casefold():
        intermedio = origen.with_name(f"{origen.name}.retroperfect-tmp")
        origen.rename(intermedio)
        intermedio.rename(destino)
        return
    origen.rename(destino)
