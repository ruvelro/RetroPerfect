#!/usr/bin/env bash
# Empaqueta RetroPerfect como aplicación de escritorio con nicegui-pack (PyInstaller).
# Por defecto genera dist/RetroPerfect/ (--onedir, arranque casi instantáneo) y un
# zip distribuible; con --onefile genera un único ejecutable (arranque más lento
# porque se autodescomprime en cada inicio).
set -euo pipefail
cd "$(dirname "$0")/.."
MODE="--onedir"
if [[ "${1:-}" == "--onefile" ]]; then MODE="--onefile"; fi
python -m pip install --quiet --upgrade pyinstaller
rm -rf build dist
nicegui-pack $MODE --name RetroPerfect scripts/retroperfect_app.py
if [[ "$MODE" == "--onedir" ]]; then
  python -c "import platform, shutil; shutil.make_archive(f'dist/RetroPerfect-{platform.system().lower()}', 'zip', 'dist', 'RetroPerfect')"
  echo "Generados dist/RetroPerfect/ y su zip distribuible"
else
  echo "Ejecutable único generado en dist/RetroPerfect"
fi
