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


async def test_gui_verify_tab_audits_scan(user: User, tmp_path) -> None:
    import binascii
    import hashlib

    from retroperfect.dat import DatIndex, parse_logiqx_dat
    from retroperfect.gui_state import state
    from retroperfect.models import Platform
    from retroperfect.scanner import scan_directory

    payload = b"OK"
    dat = tmp_path / "nes.xml"
    dat.write_text(
        '<datafile><header><name>NES</name></header>'
        f'<game name="Correcto (Europe)"><rom name="Correcto (Europe).nes" size="{len(payload)}" crc="{binascii.crc32(payload) & 0xFFFFFFFF:08x}" '
        f'md5="{hashlib.md5(payload).hexdigest()}" sha1="{hashlib.sha1(payload).hexdigest()}"/></game>'
        '<game name="Perdido (USA)"><rom name="Perdido (USA).nes" size="7" crc="deadbeef"/></game>'
        "</datafile>",
        encoding="utf-8",
    )
    roms = tmp_path / "roms"
    roms.mkdir()
    (roms / "Correcto (Europe).nes").write_bytes(payload)
    catalog = parse_logiqx_dat(dat)
    state.scan = scan_directory(roms, Platform.NES, dat_index=DatIndex(catalog), dat_path=dat)
    state.catalog = catalog

    await user.open("/")
    user.find("Verificar colección").click()
    await user.should_see("Faltantes: 1")
    await user.should_see("Verificación completada")
    issues_table = next(
        element
        for element in user.find(ui.table).elements
        if {column["name"] for column in element.columns} == {"status", "title", "detail"}
    )
    assert any(row["title"] == "Perdido" and row["status"] == "FALTA" for row in issues_table.rows)
