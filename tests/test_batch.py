"""Curar un romset de varios sistemas en una pasada.

Todo el flujo asumía una plataforma por comando, así que una colección de nueve
sistemas eran nueve invocaciones. Lo que se prueba aquí es el recorrido y, sobre
todo, que una carpeta que no se puede curar se **reporte** en vez de curarse con
el DAT equivocado.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from retroperfect.batch import discover_targets
from retroperfect.dat_manager import DatMetadata
from retroperfect.models import Platform
from retroperfect.platforms import platform_from_folder_name


def _dat_instalado(platform: str | None, nombre: str, recommended: bool = False) -> DatMetadata:
    return DatMetadata(
        id=nombre,
        path=f"/dats/{nombre}.dat",
        source="import",
        imported_at=datetime.now(UTC),
        format="logiqx",
        name=nombre,
        platform=platform,
        games=10,
        roms=10,
        parent_clone=True,
        recommended=recommended,
        regions=[],
    )


def _romset(tmp_path: Path, carpetas: list[str]) -> Path:
    raiz = tmp_path / "roms"
    raiz.mkdir()
    for nombre in carpetas:
        (raiz / nombre).mkdir()
    return raiz


# --- detección de la plataforma por el nombre de la carpeta ------------------


def test_se_reconocen_los_nombres_de_carpeta_habituales() -> None:
    """La gente no llama a sus carpetas como el catálogo de DAT."""
    esperado = {
        "nes": Platform.NES,
        "NES": Platform.NES,
        "snes": Platform.SNES,
        "SFC": Platform.SNES,
        "Super Nintendo": Platform.SNES,
        "psx": Platform.PS1,
        "PlayStation": Platform.PS1,
        "megadrive": Platform.MD,
        "Sega Genesis": Platform.MD,
        "gba": Platform.GBA,
        "Arcade": Platform.MAME,
        "ZX Spectrum": Platform.ZX_SPECTRUM,
        "Nintendo - Game Boy": Platform.GB,
    }
    for nombre, platform in esperado.items():
        assert platform_from_folder_name(nombre) == platform, nombre


def test_un_nombre_que_no_esta_claro_no_se_adivina() -> None:
    """Dar por buena una plataforma equivocada hace que el escaneo no case con
    ningún DAT y el usuario no tenga forma de saber por qué."""
    for nombre in ["mi-carpeta-rara", "", "juegos", "backup-2019"]:
        assert platform_from_folder_name(nombre) is None, nombre


# --- recorrido del romset ----------------------------------------------------


def test_cada_carpeta_recibe_su_plataforma_y_su_dat(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import batch

    raiz = _romset(tmp_path, ["nes", "snes"])
    monkeypatch.setattr(batch, "list_installed_dats", lambda: [_dat_instalado("nes", "NES DAT"), _dat_instalado("snes", "SNES DAT")])

    objetivos = discover_targets(raiz)

    assert [objetivo.name for objetivo in objetivos] == ["nes", "snes"]
    assert all(objetivo.can_curate for objetivo in objetivos)
    assert [objetivo.dat_name for objetivo in objetivos] == ["NES DAT", "SNES DAT"]
    assert objetivos[0].platform_label == "NES / Famicom"


def test_una_carpeta_sin_dat_instalado_se_reporta(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import batch

    raiz = _romset(tmp_path, ["nes", "psx"])
    monkeypatch.setattr(batch, "list_installed_dats", lambda: [_dat_instalado("nes", "NES DAT")])

    objetivos = {objetivo.name: objetivo for objetivo in discover_targets(raiz)}

    assert objetivos["nes"].can_curate
    assert not objetivos["psx"].can_curate
    assert "No hay ningún DAT de PlayStation instalado" in objetivos["psx"].skipped_reason


def test_una_carpeta_con_nombre_irreconocible_se_reporta(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import batch

    raiz = _romset(tmp_path, ["mis-cosas"])
    monkeypatch.setattr(batch, "list_installed_dats", lambda: [])

    objetivo = discover_targets(raiz)[0]

    assert not objetivo.can_curate
    assert "no se reconoce" in objetivo.skipped_reason.lower()
    assert objetivo.platform == ""


def test_se_prefiere_el_dat_recomendado_de_cada_plataforma(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import batch

    raiz = _romset(tmp_path, ["nes"])
    monkeypatch.setattr(
        batch,
        "list_installed_dats",
        lambda: [_dat_instalado("nes", "Alternativo"), _dat_instalado("nes", "El recomendado", recommended=True)],
    )

    assert discover_targets(raiz)[0].dat_name == "El recomendado"


def test_se_pueden_acotar_las_plataformas(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import batch

    raiz = _romset(tmp_path, ["nes", "snes"])
    monkeypatch.setattr(batch, "list_installed_dats", lambda: [_dat_instalado("nes", "NES DAT"), _dat_instalado("snes", "SNES DAT")])

    objetivos = {objetivo.name: objetivo for objetivo in discover_targets(raiz, only={Platform.NES})}

    assert objetivos["nes"].can_curate
    assert objetivos["snes"].skipped_reason == "Fuera de las plataformas pedidas."


def test_solo_se_miran_las_subcarpetas_directas(tmp_path: Path, monkeypatch) -> None:
    """Bajar más haría pasar por plataforma cada carpeta de región o de letra."""
    from retroperfect import batch

    raiz = _romset(tmp_path, ["nes"])
    (raiz / "nes" / "Europe").mkdir()
    (raiz / "nes" / "USA").mkdir()
    monkeypatch.setattr(batch, "list_installed_dats", lambda: [_dat_instalado("nes", "NES DAT")])

    assert [objetivo.name for objetivo in discover_targets(raiz)] == ["nes"]


def test_un_dat_sin_plataforma_detectada_no_se_asigna_a_nadie(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import batch

    raiz = _romset(tmp_path, ["nes"])
    monkeypatch.setattr(batch, "list_installed_dats", lambda: [_dat_instalado(None, "Suelto")])

    assert not discover_targets(raiz)[0].can_curate
