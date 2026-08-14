"""Integración con qBittorrent: añadir un torrent con solo los archivos que faltan.

Es la vía cómoda, no la única: cualquier otro cliente sirve igual. Con los demás
se selecciona a mano lo que RetroPerfect indique y luego se recoge lo descargado
con `collect_downloads`, que no sabe ni le importa qué cliente lo bajó.

Las credenciales no se guardan en ningún archivo: se pasan por argumento o por
las variables de entorno RETROPERFECT_QBT_USER y RETROPERFECT_QBT_PASS.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

from .download_plan import DownloadPlan
from .torrent import read_torrent

DEFAULT_URL = "http://127.0.0.1:8080"
TIMEOUT_SECONDS = 30

# En qBittorrent, prioridad 0 significa "no descargar este archivo".
PRIORITY_SKIP = 0
PRIORITY_NORMAL = 1


class TorrentClientError(RuntimeError):
    """Falla al hablar con el cliente de torrent."""


class QBittorrentClient:
    """Cliente mínimo de la Web API v2 de qBittorrent."""

    def __init__(self, base_url: str = DEFAULT_URL, username: str | None = None, password: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username if username is not None else os.environ.get("RETROPERFECT_QBT_USER")
        self.password = password if password is not None else os.environ.get("RETROPERFECT_QBT_PASS")
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v2/{path}"

    def _post(self, path: str, **kwargs) -> requests.Response:
        try:
            response = self.session.post(self._url(path), timeout=TIMEOUT_SECONDS, **kwargs)
        except requests.RequestException as exc:
            raise TorrentClientError(f"No se pudo contactar con qBittorrent en {self.base_url}: {exc}") from exc
        if response.status_code == 403:
            raise TorrentClientError("qBittorrent rechazó la petición (403). ¿Hace falta usuario y contraseña?")
        response.raise_for_status()
        return response

    def _get(self, path: str, **kwargs) -> requests.Response:
        try:
            response = self.session.get(self._url(path), timeout=TIMEOUT_SECONDS, **kwargs)
        except requests.RequestException as exc:
            raise TorrentClientError(f"No se pudo contactar con qBittorrent en {self.base_url}: {exc}") from exc
        response.raise_for_status()
        return response

    def login(self) -> None:
        """Autentica si hacen falta credenciales. Con la Web UI abierta en local, no."""
        if not self.username:
            return
        response = self._post("auth/login", data={"username": self.username, "password": self.password or ""})
        if response.text.strip() != "Ok.":
            raise TorrentClientError("qBittorrent rechazó las credenciales.")

    def version(self) -> str:
        return self._get("app/version").text.strip()

    def add_torrent(self, torrent_path: Path, save_path: str | None = None) -> None:
        """Añade el torrent en pausa, para poder deseleccionar antes de que empiece."""
        data = {"paused": "true", "stopped": "true", "autoTMM": "false"}
        if save_path:
            data["savepath"] = save_path
        with Path(torrent_path).open("rb") as handle:
            self._post("torrents/add", data=data, files={"torrents": (Path(torrent_path).name, handle, "application/x-bittorrent")})

    def files(self, info_hash: str) -> list[dict]:
        return list(self._get("torrents/files", params={"hash": info_hash}).json())

    def set_priorities(self, info_hash: str, indices: list[int], priority: int) -> None:
        if not indices:
            return
        self._post("torrents/filePrio", data={"hash": info_hash, "id": "|".join(str(index) for index in indices), "priority": priority})

    def start(self, info_hash: str) -> None:
        # `resume` en qBittorrent 4.x, `start` en 5.x: se intentan ambos.
        for endpoint in ("torrents/start", "torrents/resume"):
            try:
                self._post(endpoint, data={"hashes": info_hash})
                return
            except (TorrentClientError, requests.HTTPError):
                continue
        raise TorrentClientError("No se pudo reanudar el torrent en qBittorrent.")


def wanted_paths(plan: DownloadPlan, torrent_location: str) -> set[str]:
    """Rutas dentro del torrent que el plan quiere descargar."""
    return {
        candidate.inner_path
        for candidate in plan.candidates
        if candidate.container == "torrent" and candidate.inner_path and candidate.url == torrent_location
    }


def queue_plan(
    plan: DownloadPlan,
    torrent_path: Path,
    *,
    client: QBittorrentClient | None = None,
    save_path: str | None = None,
    start: bool = True,
) -> dict[str, int]:
    """Añade el torrent a qBittorrent con solo los archivos que faltan seleccionados.

    Devuelve cuántos archivos quedan activos y cuántos deseleccionados.
    """
    info = read_torrent(torrent_path)
    wanted = wanted_paths(plan, str(torrent_path))
    if not wanted:
        raise TorrentClientError("El plan no incluye ningún archivo de este torrent.")

    client = client or QBittorrentClient()
    client.login()
    client.add_torrent(torrent_path, save_path=save_path)

    entries = client.files(info.info_hash)
    if not entries:
        raise TorrentClientError("qBittorrent añadió el torrent pero no devuelve su lista de archivos.")

    skip: list[int] = []
    keep: list[int] = []
    for entry in entries:
        index = int(entry.get("index", entries.index(entry)))
        # qBittorrent antepone la carpeta del torrent en los multi-archivo.
        name = str(entry.get("name", ""))
        relative = name.split("/", 1)[1] if name.startswith(f"{info.name}/") else name
        (keep if relative in wanted or name in wanted else skip).append(index)

    client.set_priorities(info.info_hash, skip, PRIORITY_SKIP)
    client.set_priorities(info.info_hash, keep, PRIORITY_NORMAL)
    if start:
        client.start(info.info_hash)
    return {"seleccionados": len(keep), "descartados": len(skip)}
