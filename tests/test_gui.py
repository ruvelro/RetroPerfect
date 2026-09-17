from __future__ import annotations

import json
from pathlib import Path

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
        if {column["name"] for column in element.columns} == {"label", "kind", "location", "platform", "enabled"}
    )
    assert sources_table.rows[0]["label"] == "Mi carpeta"
    assert sources_table.rows[0]["kind"] == "local_dir"
    assert sources_table.rows[0]["enabled"] == "sí"


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


async def test_gui_lista_las_sesiones_de_papelera(user: User, tmp_path, monkeypatch) -> None:
    """Borrar mueve a la papelera; deshacerlo tenía que poder hacerse sin la terminal.

    Aquí se prueba el cableado (la tabla y el guard sin selección). La restauración
    en sí se prueba en test_trash.py: cruzar un hilo desde un handler no es fiable
    en el simulador cuando corre la suite entera.
    """
    from retroperfect import trash

    monkeypatch.chdir(tmp_path)
    original = tmp_path / "roms" / "Juego (Europe).nes"
    original.parent.mkdir(parents=True)
    session_dir = trash.trash_root() / "20260917-120000"
    session_dir.mkdir(parents=True)
    (session_dir / "Juego (Europe).nes").write_bytes(b"ROM")
    (session_dir / "index.json").write_text(
        json.dumps({"created": "2026-09-17 12:00", "files": [{"trashed": "Juego (Europe).nes", "original": str(original)}]}),
        encoding="utf-8",
    )

    await user.open("/")
    trash_table = next(
        element
        for element in user.find(ui.table).elements
        if {column["name"] for column in element.columns} == {"name", "created", "files", "size", "restorable"}
    )
    assert trash_table.rows == [
        {"name": "20260917-120000", "created": "2026-09-17 12:00", "files": 1, "size": "3 B", "restorable": "sí"}
    ]

    user.find("Restaurar sesión").click()
    await user.should_see("Selecciona la sesión que quieres restaurar")


def test_el_recuento_de_restaurados_no_cuenta_las_lineas_de_log() -> None:
    """restore_session devuelve un log (incluye omitidos y el aviso de borrado de
    la sesión), no una lista de archivos: contarlo entero infla la cifra."""
    lines = [
        "restaurado Juego (Europe).nes -> /roms/Juego (Europe).nes",
        "omitido (el original ya existe): /roms/Otro.nes",
        "sesión 20260917-120000 eliminada de la papelera",
    ]
    assert sum(1 for line in lines if line.startswith("restaurado ")) == 1
    assert len([line for line in lines if line.startswith("omitido ")]) == 1


async def test_gui_ofrece_enlazar_en_vez_de_copiar(user: User) -> None:
    """La casilla de enlaces duros vive en Plan, que arranca bloqueado por el
    gate: sin este test solo se vería visitando la pestaña con todo configurado."""
    await user.open("/")
    casilla = next(
        element for element in user.find(ui.checkbox).elements if "Enlazar en vez de copiar" in (element.text or "")
    )
    assert casilla.value is False, "enlazar no puede ser el comportamiento por defecto"


async def test_gui_todas_las_tablas_conservan_estilo_y_alineacion(user: User) -> None:
    """Candado del helper _data_table: ninguna tabla puede quedarse sin estilo, y
    cada columna centrada o a la derecha tiene que traer su slot de celda."""
    await user.open("/")
    tables = user.find(ui.table).elements
    assert len(tables) >= 20

    sin_estilo = [table for table in tables if "compact-table" not in table._classes and "rp-table-card" not in table._classes]
    assert sin_estilo == [], f"{len(sin_estilo)} tabla(s) renderizadas sin clases de estilo"

    for table in tables:
        for column in table.columns:
            if column.get("align") in {"center", "right"} and "compact-table" in table._classes:
                assert f"body-cell-{column['name']}" in table.slots, f"columna {column['name']} alineada sin slot de celda"


async def _add_torrent_source(user: User, location: Path) -> None:
    user.find("Nombre").type("Mi torrent")
    user.find("Ítem, URL o carpeta").type(str(location))
    kind_select = next(element for element in user.find(ui.select).elements if "archive_org" in (element.options or []))
    kind_select.set_value("torrent")
    user.find("Añadir fuente").click()
    await user.should_see("Fuente añadida")


async def test_gui_torrent_panel_solo_aparece_con_una_fuente_torrent(user: User, tmp_path, monkeypatch) -> None:
    """El panel de torrent estorba si no hay ninguna fuente de ese tipo."""
    from retroperfect import rom_sources

    monkeypatch.setattr(rom_sources, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(rom_sources, "data_dir", lambda: tmp_path)
    torrent_file = tmp_path / "set.torrent"
    torrent_file.write_bytes(b"d4:infod4:name3:setee")  # registrar la fuente no lo parsea

    await user.open("/")
    await user.should_not_see("Recoger lo descargado")

    await _add_torrent_source(user, torrent_file)
    await user.should_see("Recoger lo descargado")


async def test_gui_torrent_pide_un_plan_antes_de_encolar(user: User, tmp_path, monkeypatch) -> None:
    """Sin plan no hay nada que seleccionar en el cliente: tiene que decirlo, no callar."""
    from retroperfect import rom_sources

    monkeypatch.setattr(rom_sources, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(rom_sources, "data_dir", lambda: tmp_path)
    torrent_file = tmp_path / "set.torrent"
    torrent_file.write_bytes(b"d4:infod4:name3:setee")

    await user.open("/")
    await _add_torrent_source(user, torrent_file)
    user.find("Seleccionar en qBittorrent").click()
    await user.should_see("Calcula primero un plan que incluya archivos de un torrent")
    user.find("Recoger lo descargado").click()
    await user.should_see("Calcula primero un plan que incluya archivos de un torrent")
