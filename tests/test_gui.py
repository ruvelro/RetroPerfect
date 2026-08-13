from __future__ import annotations

import pytest
from nicegui import ui
from nicegui.testing import User

from retroperfect.gui import build_ui


@pytest.fixture(autouse=True)
def gui_page(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    import retroperfect.gui as gui_module

    monkeypatch.setattr(gui_module, "state", gui_module.AppState())

    @ui.page("/")
    def page() -> None:
        build_ui()


async def test_gui_renders_main_tabs(user: User) -> None:
    await user.open("/")
    await user.should_see("RetroPerfect")
    for tab in ["Plataforma", "Setup", "Biblioteca DAT", "Perfil", "Escaneo", "Plan", "Actividad"]:
        await user.should_see(tab)


async def test_gui_platform_tab_lists_systems(user: User) -> None:
    await user.open("/")
    await user.should_see("NES / Famicom")


async def test_gui_scan_requires_source(user: User) -> None:
    await user.open("/")
    user.find("Escanear colección").click()
    await user.should_see("Selecciona un origen antes de escanear.")
