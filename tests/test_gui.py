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


async def test_gui_quit_button_asks_confirmation(user: User) -> None:
    await user.open("/")
    user.find("Salir").click()
    await user.should_see("Se detendrá el servidor local")


async def test_gui_quit_button_warns_about_work_in_progress(user: User) -> None:
    from retroperfect.gui_state import busy

    await user.open("/")
    with busy("aplicando el manifiesto"):
        user.find("Salir").click()
        await user.should_see("Hay una operación en curso (aplicando el manifiesto)")


async def test_gui_download_tab_registers_a_source_from_the_form(user: User, tmp_path, monkeypatch) -> None:
    """Cobertura del cableado de la pestaña.

    El camino feliz del plan (cruce DAT/perfil/índice) se prueba a nivel de módulo en
    test_downloads.py: aquí cruzaría un hilo, y el simulador de NiceGUI no entrega su
    resultado de forma fiable cuando la suite completa está en marcha.
    """
    from retroperfect import rom_sources

    monkeypatch.setattr(rom_sources, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(rom_sources, "data_dir", lambda: tmp_path)
    mirror = tmp_path / "mirror"
    mirror.mkdir()

    await user.open("/")
    # Sin setup validado la pestaña tiene que seguir siendo accesible: las fuentes se
    # configuran antes de escanear nada, igual que en Biblioteca DAT.
    download_tab = next(element for element in user.find(ui.tab).elements if element._props.get("label") == "Descargar")
    assert "disable" not in download_tab._props

    user.find("Nombre").type("Mi carpeta")
    user.find("Ítem, URL o carpeta").type(str(mirror))
    # Hay más de un select con etiqueta "Tipo" (el filtro de Plataforma), así que se
    # localiza por sus opciones.
    kind_select = next(element for element in user.find(ui.select).elements if "archive_org" in (element.options or []))
    kind_select.set_value("local_dir")
    user.find("Añadir fuente").click()
    await user.should_see("Fuente añadida")

    assert [source.location for source in rom_sources.list_rom_sources("nes")] == [str(mirror)]
    sources_table = next(
        element
        for element in user.find(ui.table).elements
        if {column["name"] for column in element.columns} == {"label", "kind", "location", "platform"}
    )
    assert sources_table.rows[0]["label"] == "Mi carpeta"
    assert sources_table.rows[0]["kind"] == "local_dir"


async def test_gui_download_tab_requires_a_source(user: User, tmp_path, monkeypatch) -> None:
    from retroperfect import rom_sources
    from retroperfect.gui_state import state
    from retroperfect.models import DatCatalog

    monkeypatch.setattr(rom_sources, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(rom_sources, "data_dir", lambda: tmp_path)
    state.catalog = DatCatalog(name="vacio")

    await user.open("/")
    user.find("Calcular plan").click()
    await user.should_see("No hay fuentes configuradas para esta plataforma.")


async def test_gui_download_tab_requires_a_dat(user: User, tmp_path, monkeypatch) -> None:
    from retroperfect import rom_sources

    monkeypatch.setattr(rom_sources, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(rom_sources, "data_dir", lambda: tmp_path)

    await user.open("/")
    user.find("Calcular plan").click()
    await user.should_see("Necesitas un DAT cargado")
