"""Lectura y escritura de los escaneos guardados en `.retroperfect/scans/`."""
from __future__ import annotations

import json
from pathlib import Path

from .models import ScanResult
from .paths import project_state_dir

SCAN_RETENTION = 20

# Formato del archivo de escaneo. El 2 saca los juegos del DAT a una lista
# aparte y deja en cada ROM una referencia; el 1 (sin este campo) los repetía
# dentro de cada ROM y se sigue leyendo.
SCAN_FORMAT = 2


def save_scan(scan: ScanResult, state_dir: Path | None = None, keep: int = SCAN_RETENTION) -> Path:
    root = state_dir or project_state_dir()
    scans = root / "scans"
    scans.mkdir(parents=True, exist_ok=True)
    path = scans / f"{scan.id}.json"
    # Se serializa una vez y se escribe dos: `latest.json` tiene que seguir
    # siendo un escaneo completo porque es la ruta que se pasa a los comandos.
    texto = json.dumps(_payload(scan), indent=2, ensure_ascii=False)
    path.write_text(texto, encoding="utf-8")
    (scans / "latest.json").write_text(texto, encoding="utf-8")
    _prune_scans(scans, keep)
    return path


def _payload(scan: ScanResult) -> dict:
    """Escaneo serializable con cada juego del DAT escrito una sola vez.

    Cada ROM llevaba dentro su entrada completa del DAT, y esa entrada incluye
    TODAS las ROMs del juego: un juego de Redump de diez pistas repetía diez
    veces la misma entrada, y un escaneo de 20.000 archivos se iba a decenas de
    MB (por duplicado, contando `latest.json`). El índice del DAT devuelve el
    mismo objeto a todas las ROMs de un juego, así que se deduplica por
    identidad y sale gratis.
    """
    datos = scan.model_dump(mode="json", exclude={"roms"})
    catalogo: list[dict] = []
    posiciones: dict[int, int] = {}
    filas: list[dict] = []
    for rom in scan.roms:
        fila = rom.model_dump(mode="json", exclude={"dat_game"})
        if rom.dat_game is not None:
            clave = id(rom.dat_game)
            if clave not in posiciones:
                posiciones[clave] = len(catalogo)
                catalogo.append(rom.dat_game.model_dump(mode="json"))
            fila["dat_game_ref"] = posiciones[clave]
        filas.append(fila)
    return {**datos, "format": SCAN_FORMAT, "dat_games": catalogo, "roms": filas}


def _prune_scans(scans_dir: Path, keep: int) -> None:
    history = sorted(
        (item for item in scans_dir.glob("*.json") if item.name != "latest.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for stale in history[keep:]:
        stale.unlink(missing_ok=True)


def load_scan(path: Path) -> ScanResult:
    """Carga un escaneo, en el formato nuevo o en el de las versiones anteriores."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("format", None)
    catalogo = payload.pop("dat_games", None)
    if catalogo is not None:
        for fila in payload.get("roms", []):
            referencia = fila.pop("dat_game_ref", None)
            if referencia is not None and 0 <= referencia < len(catalogo):
                fila["dat_game"] = catalogo[referencia]
    return ScanResult.model_validate(payload)
