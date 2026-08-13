from __future__ import annotations

import pytest
from nicegui import ui
from nicegui.testing import User

from retroperfect.gui import build_ui


@pytest.fixture(autouse=True)
def gui_page(user: User) -> None:
    from retroperfect.gui_state import reset_state

    reset_state()

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


async def test_gui_platform_switch_rewires_all_tabs(user: User) -> None:
    await user.open("/")
    selects = list(user.find(ui.select).elements)
    platform_select = next(element for element in selects if element._props.get("label") == "Plataforma")
    platform_select.set_value("snes")
    await user.should_see("SNES / SFC")
    await user.should_see("La plataforma ha cambiado. Valida el setup y escanea de nuevo.")
