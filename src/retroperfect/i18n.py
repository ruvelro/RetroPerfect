"""Traducción de los textos que ve el usuario.

El proyecto se escribió en español y el español sigue siendo el idioma de
origen: las cadenas del código SON las claves, igual que en gettext, así que un
texto sin traducir se muestra en español en vez de romperse o salir vacío.

**Por qué un diccionario de Python y no gettext**: gettext necesita compilar
catálogos `.mo` con `msgfmt` y que esos binarios viajen dentro del paquete. Esta
aplicación se distribuye congelada con PyInstaller, donde añadir archivos de
datos es una fuente conocida de "funciona en local y no en el binario", y el
proyecto no tiene plurales que resolver (los textos ya dicen "archivo(s)", que
es el estilo de la casa). Un módulo Python por idioma se importa como cualquier
otro, se puede leer y revisar, y no necesita paso de compilación. Si algún día
hacen falta plurales de verdad, la forma de las claves es la misma y migrar a
gettext es mecánico.
"""
from __future__ import annotations

import locale
import os

# Idiomas con catálogo, en el orden en el que se ofrecen.
LANGUAGES = {
    "es": "Español",
    "en": "English",
}
SOURCE_LANGUAGE = "es"
LANGUAGE_ENV_VAR = "RETROPERFECT_LANG"

_catalog: dict[str, str] = {}
_language = SOURCE_LANGUAGE


def available_languages() -> dict[str, str]:
    return dict(LANGUAGES)


def current_language() -> str:
    return _language


def set_language(code: str | None) -> str:
    """Fija el idioma y devuelve el que ha quedado activo.

    Un código desconocido no es un error: se cae al idioma de origen, porque
    arrancar en español es mejor que no arrancar.
    """
    global _catalog, _language
    elegido = (code or "").split("-")[0].split("_")[0].lower()
    if elegido not in LANGUAGES:
        elegido = SOURCE_LANGUAGE
    _language = elegido
    _catalog = _load_catalog(elegido)
    return elegido


def _load_catalog(code: str) -> dict[str, str]:
    if code == SOURCE_LANGUAGE:
        return {}
    try:
        modulo = __import__(f"retroperfect.translations.{code}", fromlist=["CATALOG"])
    except ImportError:
        return {}
    catalogo = getattr(modulo, "CATALOG", {})
    return {clave: valor for clave, valor in catalogo.items() if valor}


def detect_language() -> str:
    """Idioma a usar: la variable de entorno manda, y si no, el del sistema."""
    forzado = os.environ.get(LANGUAGE_ENV_VAR)
    if forzado:
        return forzado
    try:
        del_sistema, _codificacion = locale.getdefaultlocale()
    except ValueError:  # algunos sistemas devuelven un locale que no se parsea
        del_sistema = None
    return del_sistema or SOURCE_LANGUAGE


def gettext(text: str) -> str:
    """Traduce `text`, o lo devuelve tal cual si no está en el catálogo."""
    return _catalog.get(text, text)


# Alias corto, el de siempre en gettext: `_("texto")`.
_ = gettext


def missing_keys(texts: list[str], code: str) -> list[str]:
    """Textos que el catálogo de `code` no traduce. Lo usa el candado de tests."""
    catalogo = _load_catalog(code)
    return [texto for texto in dict.fromkeys(texts) if texto not in catalogo]


set_language(detect_language())
