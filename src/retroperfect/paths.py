from __future__ import annotations

import os
import sys
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "RetroPerfect"

# Permite fijar a mano la carpeta de trabajo, útil para tener varias colecciones
# o para apuntar la app empaquetada a una carpeta concreta.
HOME_ENV_VAR = "RETROPERFECT_HOME"


def workspace_dir() -> Path:
    """Carpeta donde vive el estado del proyecto (escaneos, planes, papelera).

    Normalmente es el directorio actual: es lo que espera quien usa la CLI
    dentro de la carpeta de su colección. Pero la app empaquetada se abre con
    doble clic y hereda un cwd que no eligió —en macOS, `/`—, así que escribir
    ahí falla por permisos y el usuario se quedaba sin caché, sin manifiestos y
    sin papelera. En ese caso se usa una carpeta estable dentro de los datos de
    la aplicación, que el botón "Abrir carpeta del proyecto" sabe encontrar.
    """
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(override).expanduser()
    if getattr(sys, "frozen", False):
        return data_dir() / "workspace"
    return Path.cwd()


def project_state_dir(base: Path | None = None) -> Path:
    root = base or workspace_dir()
    path = root / ".retroperfect"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        if base is not None:
            raise  # la ruta la eligió quien llama: no se sustituye por otra a su espalda
        # Último recurso: un cwd sin permiso de escritura (un montaje de solo
        # lectura, una app lanzada desde una ruta rara) no debe dejar la
        # operación sin sitio donde escribir.
        path = data_dir() / "workspace" / ".retroperfect"
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

