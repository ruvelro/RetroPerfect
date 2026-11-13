"""Deshacer una aplicación: devolver la colección a como estaba antes.

Había journal y papelera, pero nada que los usara: deshacer era rehacer el
camino a mano. Esto lee el registro estructurado que deja `apply` y lo invierte
en orden inverso.

La regla de la casa se mantiene: **no se borra nada que no hayamos escrito
nosotros**. Cada operación deshacible guarda el MD5 de lo que se escribió, y si
el archivo ya no es ese —el usuario lo reemplazó, lo parcheó, lo editó— se
omite y se dice. Lo que se borró definitivamente (`--hard-delete`) no se puede
recuperar, y también se dice.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from .paths import project_state_dir

HASH_CHUNK_SIZE = 1024 * 1024


class UndoStep(BaseModel):
    """Un paso para deshacer, o el motivo por el que no se puede."""

    action: str
    detail: str
    path: str
    restore_to: str = ""
    expected_md5: str = ""
    skipped_reason: str = ""

    @property
    def can_apply(self) -> bool:
        return not self.skipped_reason


class UndoPlan(BaseModel):
    journal: str
    applied_at: str = ""
    platform: str = ""
    steps: list[UndoStep] = Field(default_factory=list)
    hard_deleted: int = 0

    @property
    def applicable(self) -> list[UndoStep]:
        return [step for step in self.steps if step.can_apply]


def journals_dir(root: Path | None = None) -> Path:
    return root or (project_state_dir() / "applied")


def list_journals(root: Path | None = None) -> list[Path]:
    """Journals de más reciente a más antiguo. El nombre empieza por la fecha."""
    carpeta = journals_dir(root)
    if not carpeta.exists():
        return []
    return sorted((item for item in carpeta.glob("*.json") if item.is_file()), reverse=True)


def latest_journal(root: Path | None = None) -> Path | None:
    journals = list_journals(root)
    return journals[0] if journals else None


def plan_undo(journal_path: Path) -> UndoPlan:
    """Qué haría falta para deshacer lo que registra este journal."""
    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{journal_path.name} no se puede leer como journal: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{journal_path.name} no parece un journal de RetroPerfect.")

    plan = UndoPlan(
        journal=str(journal_path),
        applied_at=str(payload.get("applied_at", "")),
        platform=str(payload.get("platform", "")),
    )
    registros = payload.get("reverts")
    if registros is None:
        raise ValueError(
            f"{journal_path.name} es de una versión anterior y no guarda qué deshacer. "
            "Los journals nuevos sí; este solo sirve para consultar lo que se hizo."
        )
    if payload.get("hard_delete"):
        plan.hard_deleted = sum(1 for registro in registros if registro.get("action") == "hard_delete")

    # Al revés: lo último que se hizo es lo primero que se deshace.
    for registro in reversed(list(registros)):
        step = _step_for(registro)
        if step is not None:
            plan.steps.append(step)
    return plan


def _step_for(registro: dict) -> UndoStep | None:
    accion = str(registro.get("action", ""))
    if accion == "create":
        destino = Path(str(registro.get("destination", "")))
        step = UndoStep(
            action="borrar",
            detail=f"se borra {destino.name}, que lo creó la aplicación",
            path=str(destino),
            expected_md5=str(registro.get("md5", "")),
        )
    elif accion == "move":
        destino = Path(str(registro.get("destination", "")))
        step = UndoStep(
            action="devolver",
            detail=f"vuelve a {Path(str(registro.get('source', ''))).parent}",
            path=str(destino),
            restore_to=str(registro.get("source", "")),
            expected_md5=str(registro.get("md5", "")),
        )
    elif accion == "trash":
        step = UndoStep(
            action="restaurar",
            detail=f"se saca de la papelera a {Path(str(registro.get('original', ''))).parent}",
            path=str(registro.get("trashed", "")),
            restore_to=str(registro.get("original", "")),
        )
    else:
        return None
    _check(step)
    return step


def _check(step: UndoStep) -> None:
    """Marca el paso que no se puede deshacer sin pisar algo ajeno."""
    origen = Path(step.path)
    if not origen.exists():
        step.skipped_reason = f"{origen.name} ya no está donde lo dejó la aplicación."
        return
    if step.expected_md5 and _file_md5(origen).lower() != step.expected_md5.lower():
        step.skipped_reason = f"{origen.name} ha cambiado desde que se aplicó: no se toca."
        return
    if step.restore_to and Path(step.restore_to).exists():
        step.skipped_reason = f"Ya hay un archivo en {step.restore_to}: no se sobrescribe."


def apply_undo(plan: UndoPlan) -> list[str]:
    """Deshace lo que se puede y devuelve el registro de lo hecho y lo omitido."""
    log: list[str] = []
    for step in plan.steps:
        if not step.can_apply:
            log.append(f"omitido {Path(step.path).name}: {step.skipped_reason}")
            continue
        origen = Path(step.path)
        try:
            if step.action == "borrar":
                origen.unlink()
                log.append(f"borrado {origen}")
            else:
                destino = Path(step.restore_to)
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(origen), str(destino))
                log.append(f"{'devuelto' if step.action == 'devolver' else 'restaurado'} {origen} -> {destino}")
        except OSError as exc:
            log.append(f"error al deshacer {origen.name}: {exc}")
    if plan.hard_deleted:
        log.append(f"{plan.hard_deleted} archivo(s) se borraron definitivamente y no se pueden recuperar.")
    return log


def _file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        while chunk := fh.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
