from __future__ import annotations

from pathlib import Path

from .models import ScanResult
from .paths import project_state_dir


def save_scan(scan: ScanResult, state_dir: Path | None = None) -> Path:
    root = state_dir or project_state_dir()
    scans = root / "scans"
    scans.mkdir(parents=True, exist_ok=True)
    path = scans / f"{scan.id}.json"
    path.write_text(scan.model_dump_json(indent=2), encoding="utf-8")
    (scans / "latest.json").write_text(scan.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_scan(path: Path) -> ScanResult:
    return ScanResult.model_validate_json(path.read_text(encoding="utf-8"))

