"""La versión del paquete: una sola, y la que ven los espejos públicos."""
from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest

import retroperfect
from retroperfect.http import session

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_la_version_del_modulo_y_la_del_paquete_coinciden() -> None:
    """Estuvieron desincronizadas (0.4.0 frente a 0.6.0) y el User-Agent de las
    descargas, que sale del módulo, se quedó en una versión vieja."""
    assert retroperfect.__version__ == version("retroperfect")


def test_pyproject_lee_la_version_del_modulo() -> None:
    """Si alguien vuelve a escribirla a mano en pyproject, se desincronizan."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert "version" in data["project"]["dynamic"]
    assert "version" not in data["project"]
    assert data["tool"]["hatch"]["version"]["path"] == "src/retroperfect/__init__.py"


def test_el_user_agent_lleva_la_version_actual() -> None:
    assert session().headers["User-Agent"] == f"RetroPerfect/{retroperfect.__version__}"


def test_los_classifiers_cubren_las_versiones_de_python_que_prueba_la_ci() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    ci = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
    probadas = {item.strip('"') for item in ci.read_text(encoding="utf-8").split("python-version: [")[1].split("]")[0].split(", ")}
    declaradas = {line.rsplit(" :: ", 1)[1] for line in data["project"]["classifiers"] if line.startswith("Programming Language :: Python :: 3.")}

    assert probadas <= declaradas, f"la CI prueba {sorted(probadas - declaradas)} y los classifiers no lo declaran"


def test_la_carpeta_de_trabajo_es_el_directorio_actual(tmp_path: Path, monkeypatch) -> None:
    from retroperfect.paths import workspace_dir

    monkeypatch.delenv("RETROPERFECT_HOME", raising=False)
    monkeypatch.chdir(tmp_path)

    assert workspace_dir() == tmp_path


def test_la_app_empaquetada_no_escribe_en_el_cwd_que_hereda(tmp_path: Path, monkeypatch) -> None:
    """Con doble clic en macOS el cwd es `/`: escribir ahí falla por permisos y
    el usuario se quedaba sin caché, sin manifiestos y sin papelera."""
    import sys

    from retroperfect import paths

    monkeypatch.delenv("RETROPERFECT_HOME", raising=False)
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "datos")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.chdir(Path(tmp_path.anchor))

    assert paths.workspace_dir() == tmp_path / "datos" / "workspace"
    assert paths.project_state_dir() == tmp_path / "datos" / "workspace" / ".retroperfect"


def test_retroperfect_home_fija_la_carpeta_de_trabajo(tmp_path: Path, monkeypatch) -> None:
    from retroperfect.paths import workspace_dir

    monkeypatch.setenv("RETROPERFECT_HOME", str(tmp_path / "coleccion"))

    assert workspace_dir() == tmp_path / "coleccion"


def test_un_cwd_sin_permiso_de_escritura_cae_en_los_datos_de_la_app(tmp_path: Path, monkeypatch) -> None:
    from retroperfect import paths

    monkeypatch.delenv("RETROPERFECT_HOME", raising=False)
    solo_lectura = tmp_path / "solo-lectura"
    solo_lectura.mkdir()
    solo_lectura.chmod(0o500)
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "datos")
    monkeypatch.chdir(solo_lectura)
    try:
        assert paths.project_state_dir() == tmp_path / "datos" / "workspace" / ".retroperfect"
    finally:
        solo_lectura.chmod(0o700)


def test_una_carpeta_pedida_a_mano_no_se_sustituye_por_otra(tmp_path: Path) -> None:
    """Si quien llama elige la ruta y falla, se entera: no se escribe en otro sitio."""
    from retroperfect.paths import project_state_dir

    solo_lectura = tmp_path / "ajena"
    solo_lectura.mkdir()
    solo_lectura.chmod(0o500)
    try:
        with pytest.raises(OSError):
            project_state_dir(solo_lectura)
    finally:
        solo_lectura.chmod(0o700)
