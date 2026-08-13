#!/usr/bin/env bash
# Empaqueta RetroPerfect como ejecutable independiente usando nicegui-pack (PyInstaller).
# Uso: ./scripts/build-app.sh  (desde cualquier directorio, con el venv del proyecto activo)
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install --quiet --upgrade pyinstaller
nicegui-pack --onefile --name RetroPerfect scripts/retroperfect_app.py
echo "Ejecutable generado en dist/RetroPerfect"
