from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_dir, user_data_dir


APP_NAME = "RetroPerfect"


def project_state_dir(base: Path | None = None) -> Path:
    root = base or Path.cwd()
    path = root / ".retroperfect"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    path = Path(user_data_dir(APP_NAME, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    path = Path(user_config_dir(APP_NAME, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path

