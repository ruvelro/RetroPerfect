"""Widgets y utilidades de interfaz compartidos entre pestañas."""
from __future__ import annotations

import webbrowser
from pathlib import Path

from nicegui import ui

GLOBAL_CSS = """
body { background: #f6f7f8; color: #172326; }
body.body--dark { background: #101719; color: #e8eef0; }
.q-tab-panel, .q-panel, .nicegui-content { background: transparent; }
.nicegui-content { padding: 0; }
#popup.nicegui-error-popup {
    display: none !important;
}
.q-table th, .q-table td {
    text-align: left !important;
    white-space: normal !important;
    overflow-wrap: anywhere;
    line-height: 1.25rem;
    vertical-align: top;
}
.q-table__container {
    max-width: 100%;
}
.q-table__middle {
    overflow-x: hidden;
}
.compact-table .q-table th,
.compact-table .q-table td {
    padding: 6px 8px;
    font-size: 12px;
}
.q-table th.text-center, .q-table td.text-center {
    text-align: center !important;
}
.q-table th.text-right, .q-table td.text-right {
    text-align: right !important;
}
.rp-center, .rp-center * {
    text-align: center !important;
}
.rp-right, .rp-right * {
    text-align: right !important;
}
.rp-table-card {
    width: 100%;
    min-height: 260px;
}
.rp-header {
    min-height: 76px;
    gap: 16px;
    flex-wrap: wrap;
}
.rp-platform-strip {
    width: 100%;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: 10px;
}
.rp-platform-tabs .q-tabs__content {
    flex-wrap: wrap;
    row-gap: 4px;
}
.rp-platform-tabs .q-tabs__content--align-center {
    justify-content: flex-start;
}
.rp-platform-tabs .q-tab {
    min-height: 36px;
    padding: 0 10px;
}
.rp-platform-card {
    border: 1px solid #d8e1e4;
    border-radius: 8px;
    padding: 10px;
    background: #fff;
    cursor: pointer;
    min-height: 156px;
}
.rp-platform-card:hover {
    border-color: #276a73;
    box-shadow: 0 2px 8px rgba(22, 79, 86, 0.12);
}
.rp-platform-card-active {
    border-color: #276a73;
    background: #eef7f8;
}
.rp-platform-icon {
    width: 34px;
    height: 34px;
    object-fit: contain;
    image-rendering: auto;
}
.rp-platform-field {
    display: grid;
    grid-template-columns: 52px 1fr;
    gap: 6px;
    font-size: 11px;
    line-height: 1.18rem;
}
.rp-platform-field span:first-child {
    color: #667085;
}
.rp-panel {
    background: #fff;
}
.rp-step-card {
    background: #fff;
}
.rp-theme-button {
    border: 1px solid rgba(255,255,255,.45);
    color: #fff !important;
    background: rgba(255,255,255,.10) !important;
}
body.body--dark .bg-white,
body.body--dark .rp-panel,
body.body--dark .rp-step-card,
body.body--dark .rp-platform-card,
body.body--dark .q-tab-panel,
body.body--dark .q-panel,
body.body--dark .q-page,
body.body--dark .nicegui-content,
body.body--dark .q-table__container,
body.body--dark .q-card {
    background: #172326 !important;
    color: #e8eef0 !important;
    border-color: #34494f !important;
}
body.body--dark .q-layout,
body.body--dark .q-page-container {
    background: #101719 !important;
}
body.body--dark .rp-platform-card-active {
    background: #203a40 !important;
    border-color: #5bb8c4 !important;
}
body.body--dark .rp-platform-tabs .q-tab,
body.body--dark .q-tabs {
    color: #c9d6da !important;
    background: transparent !important;
}
body.body--dark .rp-platform-tabs .q-tab--active {
    color: #ffffff !important;
}
body.body--dark .text-gray-500,
body.body--dark .text-gray-600,
body.body--dark .text-gray-700 {
    color: #a8bac0 !important;
}
body.body--dark .border-gray-200 {
    border-color: #34494f !important;
}
body.body--dark .q-table th {
    background: #203036 !important;
    color: #e8eef0 !important;
}
body.body--dark .q-table td {
    color: #e8eef0 !important;
    border-color: #34494f !important;
}
body.body--dark .q-field__control,
body.body--dark .q-field__native,
body.body--dark .q-field__label,
body.body--dark .q-field__append,
body.body--dark .q-menu,
body.body--dark .q-list {
    background: #172326 !important;
    color: #e8eef0 !important;
}
body.body--dark .q-field--outlined .q-field__control:before {
    border-color: #60777e !important;
}
body.body--dark .q-field--outlined .q-field__control:hover:before {
    border-color: #8fb2bb !important;
}
body.body--dark .q-badge {
    color: #fff;
}
"""


def _small_button(label: str, icon: str, on_click) -> ui.button:
    return ui.button(label, icon=icon, on_click=on_click).props("dense outline")


def _open_path(path: Path | str | None) -> None:
    if not path:
        return
    target = Path(path).expanduser()
    if target.exists():
        webbrowser.open(target.resolve().as_uri())


def _install_local_reconnect_guard() -> None:
    ui.add_body_html(
        """
        <script>
        (() => {
          if (window.__retroperfectReconnectGuard) return;
          window.__retroperfectReconnectGuard = true;

          const reconnectAfterMs = 7000;
          let reloadTimer = null;

          const hidePopup = () => {
            const popup = document.getElementById('popup');
            if (popup) popup.setAttribute('aria-hidden', 'true');
          };

          const scheduleReload = () => {
            hidePopup();
            if (reloadTimer !== null) return;
            reloadTimer = window.setTimeout(async () => {
              try {
                const response = await fetch(window.location.href, {
                  method: 'HEAD',
                  cache: 'no-store',
                });
                if (!response.ok) throw new Error('local server not ready');
              } catch (_) {
                reloadTimer = null;
                scheduleReload();
                return;
              }
              window.location.reload();
            }, reconnectAfterMs);
          };

          const clearReload = () => {
            if (reloadTimer !== null) {
              window.clearTimeout(reloadTimer);
              reloadTimer = null;
            }
            hidePopup();
          };

          const attach = () => {
            if (!window.socket || window.socket.__retroperfectGuardAttached) return false;
            window.socket.__retroperfectGuardAttached = true;
            window.socket.on('disconnect', scheduleReload);
            window.socket.on('connect', clearReload);
            window.socket.io?.on('reconnect', clearReload);
            window.socket.io?.on('reconnect_failed', scheduleReload);
            return true;
          };

          const interval = window.setInterval(() => {
            if (attach()) window.clearInterval(interval);
          }, 250);

          window.addEventListener('online', () => {
            if (reloadTimer !== null) window.location.reload();
          });
        })();
        </script>
        """
    )


def _path_picker(target: ui.input, *, choose: str, suffixes: set[str] | None = None) -> ui.dialog:
    dialog = ui.dialog()
    current = {"path": Path.cwd()}
    suffixes = suffixes or set()

    def allowed(path: Path) -> bool:
        return choose == "directory" or not suffixes or path.suffix.lower() in suffixes

    with dialog, ui.card().classes("w-[900px] max-w-[95vw]"):
        ui.label("Explorar archivos").classes("text-lg font-semibold")
        path_label = ui.label().classes("text-sm text-gray-600")
        entries = ui.column().classes("w-full max-h-[55vh] overflow-auto border border-gray-200 rounded-md p-2 gap-1")

        def refresh(path: Path) -> None:
            resolved = path.expanduser()
            if resolved.is_file():
                resolved = resolved.parent
            if not resolved.exists():
                resolved = Path.cwd()
            current["path"] = resolved
            path_label.text = str(resolved)
            entries.clear()
            with entries:
                if resolved.parent != resolved:
                    ui.button("..", icon="drive_folder_upload", on_click=lambda: refresh(resolved.parent)).props("flat dense").classes("justify-start w-full")
                for child in sorted(resolved.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
                    if child.name.startswith("."):
                        continue
                    if child.is_dir():
                        ui.button(child.name, icon="folder", on_click=lambda child=child: refresh(child)).props("flat dense").classes("justify-start w-full")
                    elif allowed(child):
                        ui.button(child.name, icon="description", on_click=lambda child=child: select(child)).props("flat dense").classes("justify-start w-full")

        def select(path: Path) -> None:
            target.value = str(path)
            dialog.close()

        with ui.row().classes("w-full items-center"):
            _small_button("Inicio", "home", lambda: refresh(Path.home()))
            _small_button("Proyecto", "terminal", lambda: refresh(Path.cwd()))
            ui.space()
            if choose in {"directory", "any"}:
                ui.button("Usar esta carpeta", icon="check", on_click=lambda: select(current["path"])).props("color=primary")
            ui.button("Cerrar", icon="close", on_click=dialog.close).props("flat")
        refresh(Path.cwd())
    return dialog
