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
import sys

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


# Variables del entorno que fijan el idioma, de más a menos prioritaria.
# LC_MESSAGES es la categoría de los textos y LANG el valor por defecto de
# todas. LANGUAGE puede traer una lista de preferencias ("es:en"): vale la
# primera.
_LOCALE_ENV_VARS = ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")
# "C" y "POSIX" no nombran un idioma: significan "sin locale configurado".
_NEUTRAL_LOCALES = {"c", "posix"}


def _system_language() -> str | None:
    """Idioma que declara el sistema, o None si no declara ninguno.

    Leemos el entorno en vez de llamar a `locale.getdefaultlocale()` porque esa
    función está obsoleta y, sobre todo, porque no contesta lo mismo en todas
    las versiones: con `LANG=C.UTF-8` —lo normal en un contenedor o en CI—
    Python 3.11 se inventa `en_US`, mientras que de 3.12 en adelante devuelve
    `C`. La misma máquina abría la interfaz en inglés o en español según con
    qué Python se arrancara.
    """
    for variable in _LOCALE_ENV_VARS:
        valor = os.environ.get(variable, "").split(":")[0].strip()
        if not valor:
            continue
        idioma = valor.split(".")[0].split("@")[0]
        return None if idioma.lower() in _NEUTRAL_LOCALES else idioma
    return _windows_language()


def _windows_language() -> str | None:
    """Windows no usa las variables POSIX: hay que preguntarle al sistema."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except Exception:  # pragma: no cover - solo se ejecuta en Windows
        return None
    return locale.windows_locale.get(lcid)


def detect_language() -> str:
    """Idioma a usar: la variable de entorno manda, y si no, el del sistema.

    Sin nada que lo diga, el idioma de origen. Un sistema en `C` no está
    pidiendo inglés: está diciendo que no tiene preferencia.
    """
    forzado = os.environ.get(LANGUAGE_ENV_VAR)
    if forzado:
        return forzado
    return _system_language() or SOURCE_LANGUAGE


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
