"""Configuración común de la suite.

El idioma se fija aquí a propósito: los tests comprueban textos en español, y
sin esto el resultado dependía del locale de la máquina. Un runner con
`LANG=C.UTF-8` y Python 3.11 abría la interfaz en inglés y hacía fallar veinte
tests que no tenían nada roto.
"""
from __future__ import annotations

import pytest

from retroperfect.i18n import SOURCE_LANGUAGE, current_language, set_language

pytest_plugins = ["nicegui.testing.user_plugin"]


@pytest.fixture(autouse=True)
def idioma_de_origen():
    """Cada test arranca en el idioma de origen y lo deja como estaba.

    Va antes que los fixtures de cada módulo, así que la GUI que construya
    `reset_state()` también nace en español.
    """
    anterior = current_language()
    set_language(SOURCE_LANGUAGE)
    yield
    set_language(anterior)
