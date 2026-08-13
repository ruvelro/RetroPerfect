"""Gestión de la papelera del proyecto (.retroperfect/trash): listar, restaurar y vaciar."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from pydantic import BaseModel

from .paths import project_state_dir


class TrashSession(BaseModel):
    name: str
    path: str
    created: str
    files: int
    total_size: int
    restorable: bool


def trash_root(root: Path | None = None) -> Path:
    return root or (project_state_dir() / "trash")


def list_sessions(root: Path | None = None) -> list[TrashSession]:
    base = trash_root(root)
    sessions: list[TrashSession] = []
    if not base.exists():
        return sessions
    for session_dir in sorted(base.iterdir(), reverse=True):
        if not session_dir.is_dir():
            continue
        index_path = session_dir / "index.json"
        created = ""
        if index_path.exists():
            try:
                created = json.loads(index_path.read_text(encoding="utf-8")).get("created", "")
            except (OSError, json.JSONDecodeError):
                created = ""
        files = [item for item in session_dir.iterdir() if item.is_file() and item.name != "index.json"]
        sessions.append(
            TrashSession(
                name=session_dir.name,
                path=str(session_dir),
                created=created,
                files=len(files),
                total_size=sum(item.stat().st_size for item in files),
                restorable=index_path.exists(),
            )
        )
    return sessions


def restore_session(name: str, root: Path | None = None) -> list[str]:
    session_dir = trash_root(root) / name
    index_path = session_dir / "index.json"
    if not session_dir.is_dir():
        raise RuntimeError(f"No existe la sesión de papelera '{name}'.")
    if not index_path.exists():
        raise RuntimeError(f"La sesión '{name}' no tiene índice de restauración; restaura manualmente desde {session_dir}.")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    log: list[str] = []
    remaining = 0
    for entry in index.get("files", []):
        trashed = session_dir / entry["trashed"]
        original = Path(entry["original"])
        if not trashed.exists():
            log.append(f"omitido (ya no está en la papelera): {entry['trashed']}")
            continue
        if original.exists():
            log.append(f"omitido (el original ya existe): {original}")
            remaining += 1
            continue
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(trashed), str(original))
        log.append(f"restaurado {entry['trashed']} -> {original}")
    if remaining == 0:
        shutil.rmtree(session_dir, ignore_errors=True)
        log.append(f"sesión {name} eliminada de la papelera")
    return log


def empty_trash(root: Path | None = None) -> int:
    base = trash_root(root)
    if not base.exists():
        return 0
    removed = 0
    for session_dir in base.iterdir():
        if session_dir.is_dir():
            removed += sum(1 for item in session_dir.rglob("*") if item.is_file() and item.name != "index.json")
            shutil.rmtree(session_dir, ignore_errors=True)
    return removed
