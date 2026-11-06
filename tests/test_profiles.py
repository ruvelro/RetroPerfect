"""Resolución de perfiles: por nombre, por nombre guardado y por ruta."""
from __future__ import annotations

from pathlib import Path

import pytest

from retroperfect import profile as profile_module
from retroperfect.models import ExportLayout
from retroperfect.profile import DEFAULT_PROFILE, RECOMMENDED_PROFILES, available_profile_names, load_profile, save_profile


def test_un_perfil_recomendado_se_carga_por_su_nombre() -> None:
    """La CLI solo entendía "default" y rutas, así que los perfiles que anuncia
    el README morían con un FileNotFoundError."""
    cargado = load_profile("1G1R + RA")

    assert cargado.name == "1G1R + RA"
    assert cargado.auto_patch_ra is True
    assert cargado.export_layout == ExportLayout.ORGANIZED


def test_el_nombre_del_perfil_no_distingue_mayusculas_ni_espacios_de_sobra() -> None:
    assert load_profile("  usa-FIRST ").name == "USA-first"


def test_default_sigue_funcionando_y_no_se_comparte_el_objeto() -> None:
    cargado = load_profile("default")

    assert cargado == DEFAULT_PROFILE
    cargado.outputs[0].strict_1g1r = not cargado.outputs[0].strict_1g1r
    assert load_profile("default") == DEFAULT_PROFILE, "se devolvió el perfil global y alguien lo mutó"


def test_una_ruta_tiene_prioridad_sobre_el_nombre(tmp_path: Path) -> None:
    ruta = tmp_path / "1G1R + RA.yaml"
    save_profile(RECOMMENDED_PROFILES["USA-first"].model_copy(update={"name": "mio"}), ruta)

    assert load_profile(ruta).name == "mio"


def test_un_perfil_guardado_se_carga_por_su_nombre(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(profile_module, "profiles_dir", lambda: tmp_path)
    save_profile(RECOMMENDED_PROFILES["USA-first"].model_copy(update={"name": "El mío"}), tmp_path / "el-mio.yaml")

    assert load_profile("El mío").name == "El mío"
    assert "El mío" in available_profile_names()


def test_un_nombre_inexistente_dice_cuales_hay() -> None:
    with pytest.raises(ValueError, match="1G1R \\+ RA"):
        load_profile("perfil que no existe")
