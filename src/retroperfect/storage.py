from __future__ import annotations

from pathlib import Path

from .models import ScanResult
from .paths import project_state_dir

SCAN_RETENTION = 20


def save_scan(scan: ScanResult, state_dir: Path | None = None, keep: int = SCAN_RETENTION) -> Path:
    root = state_dir or project_state_dir()
    scans = root / "scans"
    scans.mkdir(parents=True, exist_ok=True)
    path = scans / f"{scan.id}.json"
    path.write_text(scan.model_dump_json(indent=2), encoding="utf-8")
    (scans / "latest.json").write_text(scan.model_dump_json(indent=2), encoding="utf-8")
    _prune_scans(scans, keep)
    return path


def _prune_scans(scans_dir: Path, keep: int) -> None:
    history = sorted(
        (item for item in scans_dir.glob("*.json") if item.name != "latest.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for stale in history[keep:]:
        stale.unlink(missing_ok=True)


def load_scan(path: Path) -> ScanResult:
    return ScanResult.model_validate_json(path.read_text(encoding="utf-8"))

