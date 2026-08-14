"""Cierre de la aplicación: salida explícita y apagado automático por inactividad.

Al empaquetarse como .app o .exe no hay terminal ni icono en el Dock donde
cerrar el proceso, así que la GUI tiene que poder terminarse a sí misma.
"""
from __future__ import annotations

import asyncio
import time

from nicegui import Client, app, ui

from .gui_state import state

IDLE_TIMEOUT_SECONDS = 60.0
IDLE_CHECK_SECONDS = 5.0

# Margen extra al arrancar: si el navegador no llega a conectarse nunca
# (por ejemplo, porque falló al abrirse), la app no se queda colgada para siempre.
STARTUP_GRACE_MULTIPLIER = 3

_FAREWELL_JS = """
window.__retroperfectQuitting = true;
document.body.innerHTML = `
  <div style="font-family:Inter,system-ui,-apple-system,sans-serif;display:flex;
              align-items:center;justify-content:center;height:100vh;margin:0;
              background:#f6f7f8;color:#172326;text-align:center">
    <div>
      <div style="font-size:1.6rem;font-weight:600;color:#276a73">RetroPerfect se ha cerrado</div>
      <div style="margin-top:.6rem;opacity:.75">Ya puedes cerrar esta pestaña.</div>
    </div>
  </div>`;
"""

_idle_deadline: float | None = None


def connected_clients() -> int:
    """Navegadores con conexión viva (no cuenta pestañas ya cerradas)."""
    return sum(1 for client in Client.instances.values() if getattr(client, "has_socket_connection", False))


def busy_reason() -> str | None:
    """Describe la operación en curso que desaconseja cerrar, o None si no hay ninguna."""
    if state.busy_operations:
        return ", ".join(sorted(state.busy_operations))
    if state.scan_progress.get("phase") in {"preparing", "start", "scan"}:
        return "escaneo en curso"
    if state.ra_details_progress.get("running"):
        return "sincronización de RetroAchievements en curso"
    return None


def _notify_clients_of_shutdown() -> None:
    """Avisa a todas las pestañas para que el guard de reconexión no reintente."""
    for client in list(Client.instances.values()):
        if not getattr(client, "has_socket_connection", False):
            continue
        try:
            with client:
                ui.run_javascript(_FAREWELL_JS)
        except Exception:  # noqa: BLE001 - una pestaña muerta no debe impedir el cierre
            continue


async def request_shutdown() -> None:
    """Cierra la aplicación avisando antes a los navegadores conectados."""
    _notify_clients_of_shutdown()
    await asyncio.sleep(0.4)  # margen para que el aviso llegue antes de matar el servidor
    app.shutdown()


def install_idle_shutdown(timeout_seconds: float = IDLE_TIMEOUT_SECONDS) -> None:
    """Apaga la aplicación cuando no queda ningún navegador conectado."""
    global _idle_deadline
    _idle_deadline = time.monotonic() + timeout_seconds * STARTUP_GRACE_MULTIPLIER

    def _postpone() -> None:
        global _idle_deadline
        _idle_deadline = time.monotonic() + timeout_seconds

    def _on_connect() -> None:
        global _idle_deadline
        _idle_deadline = None

    app.on_connect(_on_connect)
    app.on_disconnect(_postpone)

    def _check() -> None:
        global _idle_deadline
        if connected_clients() > 0:
            _idle_deadline = None
            return
        if _idle_deadline is None:
            _postpone()
            return
        if busy_reason():
            _postpone()
            return
        if time.monotonic() >= _idle_deadline:
            app.shutdown()

    app.timer(IDLE_CHECK_SECONDS, _check)
