"""Punto de entrada para empaquetar la GUI como aplicación de escritorio (nicegui-pack).

freeze_support debe ejecutarse antes de importar nicegui: sin él, la app
congelada con PyInstaller se relanza a sí misma al arrancar.
"""
import multiprocessing

multiprocessing.freeze_support()

from retroperfect.gui import run  # noqa: E402

if __name__ == "__main__":
    run()
