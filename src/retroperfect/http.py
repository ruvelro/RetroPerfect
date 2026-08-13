"""Sesión HTTP compartida con reintentos para todas las descargas de la aplicación."""
from __future__ import annotations

import threading

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT_SECONDS = 60

_session: requests.Session | None = None
_session_lock = threading.Lock()


def session() -> requests.Session:
    global _session
    with _session_lock:
        if _session is None:
            # 429 queda fuera a propósito: el cliente de RetroAchievements gestiona
            # su propio rate-limit respetando el header retry-after.
            retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504], allowed_methods=["GET"])
            adapter = HTTPAdapter(max_retries=retry)
            fresh = requests.Session()
            fresh.mount("https://", adapter)
            fresh.mount("http://", adapter)
            fresh.headers["User-Agent"] = "RetroPerfect/0.1"
            _session = fresh
    return _session


def http_get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT_SECONDS)
    return session().get(url, **kwargs)
