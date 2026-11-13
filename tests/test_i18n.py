"""Traducción de la interfaz.

El test importante de este archivo es el candado: recorre el código de la GUI,
saca todas las cadenas que pasan por `_()` y comprueba que el catálogo inglés
las tiene. Sin él, una cadena nueva se queda en español sin que nadie se entere
y la interfaz acaba medio traducida, que es peor que monolingüe.
"""
from __future__ import annotations

import ast
from pathlib import Path

from retroperfect import i18n
from retroperfect.i18n import LANGUAGES, SOURCE_LANGUAGE, available_languages, current_language, missing_keys, set_language

RAIZ = Path(__file__).resolve().parent.parent / "src" / "retroperfect"


def _archivos_de_interfaz() -> list[Path]:
    return sorted(RAIZ.glob("gui*.py")) + sorted((RAIZ / "gui_tabs").glob("*.py")) + sorted((RAIZ / "gui_rows").glob("*.py"))


def cadenas_traducibles() -> list[str]:
    """Textos literales que la interfaz pasa por `_()`.

    Incluye las descripciones de los órdenes de sincronización, que viven en
    `device_sync` porque también las usa la línea de comandos.
    """
    from retroperfect.device_sync import SYNC_ORDERS

    encontradas: list[str] = list(SYNC_ORDERS.values())
    for ruta in _archivos_de_interfaz():
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == "_" and nodo.args:
                argumento = nodo.args[0]
                if isinstance(argumento, ast.Constant) and isinstance(argumento.value, str):
                    encontradas.append(argumento.value)
    return encontradas


# --- el candado --------------------------------------------------------------


def test_el_catalogo_ingles_cubre_toda_la_interfaz() -> None:
    cadenas = cadenas_traducibles()

    assert len(cadenas) > 300, "el extractor no está encontrando las cadenas de la interfaz"
    faltan = missing_keys(cadenas, "en")
    assert faltan == [], f"{len(faltan)} cadena(s) sin traducir al inglés: {faltan[:5]}"


def test_toda_cadena_visible_pasa_por_la_traduccion() -> None:
    """Candado del cableado: un literal suelto en un widget no se traduce nunca.

    Mira las llamadas a widgets de NiceGUI y las etiquetas de columna: si
    alguien añade `ui.label("Texto")` en vez de `ui.label(_("Texto"))`, aquí se
    ve.
    """
    widgets = {"label", "button", "tab", "input", "select", "checkbox", "number", "badge", "textarea", "radio", "toggle"}
    sueltas: list[str] = []
    for ruta in _archivos_de_interfaz():
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) and nodo.func.attr in widgets and nodo.args:
                argumento = nodo.args[0]
                if isinstance(argumento, ast.Constant) and isinstance(argumento.value, str) and any(c.isalpha() for c in argumento.value):
                    sueltas.append(f"{ruta.name}: {argumento.value[:60]}")
            if isinstance(nodo, ast.Dict):
                for clave, valor in zip(nodo.keys, nodo.values, strict=True):
                    if (
                        isinstance(clave, ast.Constant)
                        and clave.value == "label"
                        and isinstance(valor, ast.Constant)
                        and isinstance(valor.value, str)
                        and any(c.isalpha() for c in valor.value)
                    ):
                        sueltas.append(f"{ruta.name}: columna {valor.value[:40]}")

    assert sueltas == [], f"{len(sueltas)} literal(es) sin _(): {sueltas[:5]}"


# --- el mecanismo ------------------------------------------------------------


def test_sin_traduccion_se_devuelve_el_texto_en_espanol() -> None:
    """El español es el idioma de origen: una clave que falte no rompe nada."""
    set_language("en")

    assert i18n.gettext("Esto no está en ningún catálogo") == "Esto no está en ningún catálogo"


def test_el_catalogo_ingles_traduce_de_verdad() -> None:
    set_language("en")

    assert i18n.gettext("Escaneo") == "Scan"
    assert i18n.gettext("Papelera") == "Trash"
    assert i18n.gettext("Verificar colección") == "Verify collection"


def test_en_espanol_el_texto_sale_tal_cual() -> None:
    set_language("es")

    assert i18n.gettext("Escaneo") == "Escaneo"
    assert current_language() == "es"


def test_un_idioma_desconocido_cae_al_de_origen() -> None:
    """Arrancar en español es mejor que no arrancar."""
    assert set_language("klingon") == SOURCE_LANGUAGE
    assert set_language(None) == SOURCE_LANGUAGE
    assert set_language("") == SOURCE_LANGUAGE


def test_se_acepta_el_locale_completo_del_sistema() -> None:
    """`locale` devuelve cosas como en_GB o es-ES, no solo el idioma."""
    assert set_language("en_GB") == "en"
    assert set_language("en-US") == "en"
    assert set_language("es_ES.UTF-8") == "es"


def test_la_variable_de_entorno_manda_sobre_el_sistema(monkeypatch) -> None:
    monkeypatch.setenv(i18n.LANGUAGE_ENV_VAR, "en")

    assert i18n.detect_language() == "en"

    monkeypatch.delenv(i18n.LANGUAGE_ENV_VAR)
    assert i18n.detect_language() is not None


def test_un_sistema_sin_idioma_no_se_interpreta_como_ingles(monkeypatch) -> None:
    """El fallo que tumbó la CI: `LANG=C.UTF-8` no es una petición de inglés.

    Python 3.11 devolvía `en_US` para ese locale y 3.12 en adelante `C`, así
    que la interfaz salía en un idioma u otro según la versión.
    """
    monkeypatch.delenv(i18n.LANGUAGE_ENV_VAR, raising=False)
    for variable in i18n._LOCALE_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)

    assert i18n.detect_language() == SOURCE_LANGUAGE, "sin locale, el idioma de origen"

    for neutro in ("C", "C.UTF-8", "POSIX", "c.utf8"):
        monkeypatch.setenv("LANG", neutro)
        assert i18n.detect_language() == SOURCE_LANGUAGE, f"{neutro} no es un idioma"


def test_el_idioma_del_sistema_se_respeta(monkeypatch) -> None:
    monkeypatch.delenv(i18n.LANGUAGE_ENV_VAR, raising=False)
    for variable in i18n._LOCALE_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)

    monkeypatch.setenv("LANG", "en_GB.UTF-8")
    assert i18n.detect_language() == "en_GB"

    # LANGUAGE trae una lista de preferencias y manda sobre LANG.
    monkeypatch.setenv("LANGUAGE", "fr_FR:es_ES")
    assert i18n.detect_language() == "fr_FR"

    # LC_ALL manda sobre todas, incluso para desactivar el idioma.
    monkeypatch.setenv("LC_ALL", "C")
    assert i18n.detect_language() == SOURCE_LANGUAGE


def test_los_idiomas_ofrecidos_tienen_catalogo() -> None:
    assert set(available_languages()) == set(LANGUAGES)
    for code in LANGUAGES:
        if code == SOURCE_LANGUAGE:
            continue
        assert missing_keys(["Escaneo"], code) == [], f"{code} no traduce ni lo más básico"


# --- las etiquetas que son opciones de un desplegable ------------------------


def test_las_etiquetas_de_opciones_cambian_con_el_idioma() -> None:
    """Si fueran diccionarios de módulo, el idioma quedaría fijado al importar
    y el selector de la cabecera no cambiaría nada."""
    from retroperfect.device_sync import sync_order_labels
    from retroperfect.gui_rows import action_labels, container_labels
    from retroperfect.gui_tabs.verify import status_filters

    set_language("es")
    en_espanol = (action_labels(), container_labels(), status_filters(), sync_order_labels())
    set_language("en")
    en_ingles = (action_labels(), container_labels(), status_filters(), sync_order_labels())

    for espanol, ingles in zip(en_espanol, en_ingles, strict=True):
        assert set(espanol) == set(ingles), "las claves son parte de la interfaz de comandos: no se traducen"
        assert espanol != ingles, "los textos visibles sí tienen que cambiar"
    assert en_ingles[0]["copy"] == "Copy files"
