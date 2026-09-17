"""Funciones puras de las pestañas, probadas sin levantar la GUI.

La cobertura de `build()` vive en test_gui.py con el simulador de NiceGUI; aquí
van los helpers de módulo, que son lógica normal y no necesitan navegador.
"""
from __future__ import annotations

from retroperfect.download_plan import DownloadCandidate, DownloadPlan
from retroperfect.gui_state import busy, guarded, state
from retroperfect.gui_tabs.download import _selected_plan, _source_id
from retroperfect.models import Platform


class _Label:
    """Sustituto de ui.label: solo necesita el atributo text."""

    def __init__(self) -> None:
        self.text = ""


def _candidate(url: str, title: str, container: str = "http") -> DownloadCandidate:
    return DownloadCandidate(
        group_key=title.lower(),
        game_name=title,
        title=title,
        source_id="fuente",
        file_name=f"{title}.zip",
        url=url,
        size=1024,
        confidence="hash",
        container=container,
    )


def _plan(*candidates: DownloadCandidate) -> DownloadPlan:
    return DownloadPlan(platform=Platform.NES, candidates=list(candidates))


def test_selected_plan_sin_seleccion_devuelve_el_plan_entero() -> None:
    plan = _plan(_candidate("http://a", "A"), _candidate("http://b", "B"))
    assert _selected_plan(plan, None) is plan
    assert _selected_plan(plan, []) is plan


def test_selected_plan_acota_a_las_filas_marcadas() -> None:
    plan = _plan(_candidate("http://a", "A"), _candidate("http://b", "B"))
    acotado = _selected_plan(plan, [{"url": "http://b"}])
    assert [candidate.title for candidate in acotado.candidates] == ["B"]
    # el plan original no se toca: la tabla puede volver a marcarse
    assert len(plan.candidates) == 2


def test_source_id_normaliza_el_nombre_y_cuelga_la_plataforma() -> None:
    assert _source_id("Backup NAS", "nes") == "backup-nas-nes"
    # los acentos son alfanuméricos y se conservan; solo caen signos y espacios
    assert _source_id("  Mi Ítem!! ", None) == "mi-ítem-all"
    # un nombre sin caracteres útiles no puede quedarse sin id
    assert _source_id("///", "snes") == "fuente-snes"


def test_guarded_reporta_el_error_y_libera_la_marca_de_ocupado() -> None:
    """Un fallo dentro del guard no debe dejar la app marcada como ocupada:
    si no, el apagado por inactividad no vuelve a dispararse nunca."""
    status = _Label()
    state.busy_operations.clear()
    with guarded(status, "Error al verificar", busy_label="verificación"):
        raise ValueError("el DAT no cuadra")
    assert status.text == "Error al verificar: el DAT no cuadra"
    assert state.busy_operations == {}
    assert state.activity[0]["level"] == "ERROR"


def test_guarded_marca_la_operacion_mientras_dura() -> None:
    status = _Label()
    state.busy_operations.clear()
    with guarded(status, "Error", busy_label="escaneo"):
        assert state.busy_operations == {"escaneo": 1}
    assert state.busy_operations == {}
    assert status.text == ""


def test_busy_anidado_cuenta_las_veces_y_no_se_libera_antes_de_tiempo() -> None:
    state.busy_operations.clear()
    with busy("descarga"):
        with busy("descarga"):
            assert state.busy_operations == {"descarga": 2}
        assert state.busy_operations == {"descarga": 1}
    assert state.busy_operations == {}
