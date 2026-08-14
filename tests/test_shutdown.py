from __future__ import annotations

import pytest

from retroperfect.gui_shutdown import busy_reason
from retroperfect.gui_state import busy, state


@pytest.fixture(autouse=True)
def clean_state():
    state.busy_operations.clear()
    state.scan_progress = {"phase": "idle"}
    state.ra_details_progress = {"running": False}
    yield
    state.busy_operations.clear()


def test_busy_reason_none_when_idle() -> None:
    assert busy_reason() is None


def test_busy_marks_and_clears_operation() -> None:
    with busy("aplicando el manifiesto"):
        assert busy_reason() == "aplicando el manifiesto"
    assert busy_reason() is None
    assert state.busy_operations == {}


def test_busy_supports_nesting_and_concurrency() -> None:
    with busy("descarga"):
        with busy("descarga"):
            assert state.busy_operations["descarga"] == 2
        # la operación exterior sigue viva
        assert busy_reason() == "descarga"
    assert busy_reason() is None


def test_busy_reason_lists_several_operations() -> None:
    with busy("escaneo"), busy("descarga"):
        assert busy_reason() == "descarga, escaneo"


def test_busy_clears_even_if_operation_falla() -> None:
    with pytest.raises(RuntimeError), busy("aplicando el manifiesto"):
        raise RuntimeError("boom")
    assert busy_reason() is None


def test_busy_reason_detects_scan_in_progress() -> None:
    state.scan_progress = {"phase": "scan"}
    assert busy_reason() == "escaneo en curso"
    state.scan_progress = {"phase": "done"}
    assert busy_reason() is None


def test_busy_reason_detects_ra_sync() -> None:
    state.ra_details_progress = {"running": True}
    assert busy_reason() == "sincronización de RetroAchievements en curso"
