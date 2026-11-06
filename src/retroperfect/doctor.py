"""Estado de la instalación: lo primero que se pide en un informe de fallo.

`diagnostics.py` audita la colección; esto audita la herramienta. Son preguntas
distintas: qué versión corre, dónde escribe, qué formatos puede leer y qué hay
configurado. RetroPerfect se distribuye en binarios sin firmar que la gente
descarga de Releases, así que sin esto la primera respuesta a cualquier problema
era pedir media docena de datos a mano.
"""
from __future__ import annotations

import platform as plataforma_sistema
import sys
from pathlib import Path

from . import __version__
from .diagnostics import DiagnosticRow
from .models import Platform
from .paths import HOME_ENV_VAR, config_dir, data_dir, project_state_dir, workspace_dir


def build_doctor_rows() -> list[DiagnosticRow]:
    """Filas con el estado de la instalación, en el mismo formato que el resto."""
    return [
        *_version_rows(),
        *_workspace_rows(),
        *_optional_dependency_rows(),
        *_configuration_rows(),
    ]


def _version_rows() -> list[DiagnosticRow]:
    congelada = getattr(sys, "frozen", False)
    return [
        DiagnosticRow(status="INFO", item="RetroPerfect", detail=__version__),
        DiagnosticRow(status="INFO", item="Python", detail=f"{plataforma_sistema.python_version()} ({sys.executable})"),
        DiagnosticRow(status="INFO", item="Sistema", detail=f"{plataforma_sistema.system()} {plataforma_sistema.release()} ({plataforma_sistema.machine()})"),
        DiagnosticRow(
            status="INFO",
            item="Instalación",
            detail="aplicación empaquetada" if congelada else "paquete de Python",
            recommendation="" if congelada else "Actualiza con pip install -U retroperfect",
        ),
    ]


def _workspace_rows() -> list[DiagnosticRow]:
    trabajo = workspace_dir()
    filas = [
        DiagnosticRow(
            status="INFO",
            item="Carpeta de trabajo",
            detail=str(trabajo),
            recommendation=f"Se puede fijar con la variable {HOME_ENV_VAR}",
        )
    ]
    try:
        estado = project_state_dir()
        escribible = _comprobar_escritura(estado)
    except OSError as exc:
        filas.append(DiagnosticRow(status="MISS", item="Estado del proyecto", detail=f"no se puede crear: {exc}", recommendation=f"Elige otra carpeta con {HOME_ENV_VAR}"))
        return filas
    filas.append(
        DiagnosticRow(
            status="OK" if escribible else "MISS",
            item="Estado del proyecto",
            detail=str(estado) if escribible else f"{estado} (sin permiso de escritura)",
            recommendation="" if escribible else f"Elige otra carpeta con {HOME_ENV_VAR}",
        )
    )
    filas.append(DiagnosticRow(status="INFO", item="Configuración", detail=str(config_dir())))
    filas.append(DiagnosticRow(status="INFO", item="Datos y cachés", detail=str(data_dir())))
    for nombre, carpeta in [("Papelera", estado / "trash"), ("Escaneos", estado / "scans")]:
        filas.append(DiagnosticRow(status="INFO", item=nombre, detail=_tamano_carpeta(carpeta)))
    cache = estado / "scan-cache.sqlite3"
    filas.append(
        DiagnosticRow(
            status="INFO",
            item="Caché de hashes",
            detail=_human(cache.stat().st_size) if cache.exists() else "vacía (se crea al escanear)",
        )
    )
    return filas


def _optional_dependency_rows() -> list[DiagnosticRow]:
    """Lo que la herramienta puede leer depende de qué ruedas estén instaladas."""
    from .chd import chd_available

    filas = [
        DiagnosticRow(
            status="OK" if chd_available() else "WARN",
            item="CHD (chdimage)",
            detail="disponible" if chd_available() else "no instalado",
            recommendation="" if chd_available() else "Sin él, los .chd se ignoran al escanear: pip install chdimage",
        )
    ]
    for etiqueta, modulo, para_que in [("7z (py7zr)", "py7zr", "leer romsets en .7z"), ("xdelta (pyxdelta)", "pyxdelta", "aplicar parches xdelta/VCDIFF")]:
        disponible = _importable(modulo)
        filas.append(
            DiagnosticRow(
                status="OK" if disponible else "WARN",
                item=etiqueta,
                detail="disponible" if disponible else "no instalado",
                recommendation="" if disponible else f"Hace falta para {para_que}",
            )
        )
    return filas


def _configuration_rows() -> list[DiagnosticRow]:
    from .dat_manager import list_installed_dats
    from .ra import credentials_path, ra_cache_count
    from .rom_sources import list_rom_sources

    filas: list[DiagnosticRow] = []
    try:
        dats = list_installed_dats()
    except OSError as exc:
        dats = []
        filas.append(DiagnosticRow(status="WARN", item="Biblioteca DAT", detail=f"no se pudo leer: {exc}"))
    else:
        filas.append(
            DiagnosticRow(
                status="OK" if dats else "WARN",
                item="Biblioteca DAT",
                detail=f"{len(dats)} DAT(s) instalados" if dats else "ninguno",
                recommendation="" if dats else "Descarga uno con dat-download o impórtalo con dat-import",
            )
        )
    fuentes = list_rom_sources()
    filas.append(
        DiagnosticRow(
            status="INFO",
            item="Fuentes de romsets",
            detail=f"{sum(1 for fuente in fuentes if fuente.enabled)} activa(s) de {len(fuentes)}" if fuentes else "ninguna (las añades tú)",
        )
    )
    # Nunca el contenido: la clave de API es del usuario y no tiene que salir
    # en un informe que va a pegar en un issue.
    filas.append(
        DiagnosticRow(
            status="OK" if credentials_path().exists() else "INFO",
            item="Credenciales RetroAchievements",
            detail="configuradas" if credentials_path().exists() else "sin configurar",
            recommendation="" if credentials_path().exists() else "Solo hacen falta para las funciones de RetroAchievements",
        )
    )
    cacheadas = sum(ra_cache_count(platform) for platform in _platforms_con_cache())
    filas.append(DiagnosticRow(status="INFO", item="Hashes RA en caché", detail=f"{cacheadas}" if cacheadas else "ninguno (sincroniza con sync-ra)"))
    return filas


def _platforms_con_cache() -> list[Platform]:
    """Plataformas que tienen filas en la caché RA, consultando la tabla una vez."""
    from .ra import init_cache

    conn = init_cache()
    try:
        filas = conn.execute("SELECT DISTINCT platform FROM ra_hashes").fetchall()
    finally:
        conn.close()
    plataformas = []
    for (valor,) in filas:
        try:
            plataformas.append(Platform(valor))
        except ValueError:
            continue  # una plataforma que ya no existe en el catálogo no es un error
    return plataformas


def _importable(nombre: str) -> bool:
    from importlib.util import find_spec

    try:
        return find_spec(nombre) is not None
    except (ImportError, ValueError):
        return False


def _comprobar_escritura(carpeta: Path) -> bool:
    prueba = carpeta / ".doctor-escritura"
    try:
        prueba.write_text("ok", encoding="utf-8")
    except OSError:
        return False
    prueba.unlink(missing_ok=True)
    return True


def _tamano_carpeta(carpeta: Path) -> str:
    if not carpeta.exists():
        return "vacía"
    archivos = [item for item in carpeta.rglob("*") if item.is_file()]
    if not archivos:
        return "vacía"
    return f"{len(archivos)} archivo(s), {_human(sum(item.stat().st_size for item in archivos))}"


def _human(value: int) -> str:
    size = float(value)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
