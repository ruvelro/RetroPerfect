#!/usr/bin/env bash
# Empaqueta RetroPerfect como aplicación de escritorio con nicegui-pack (PyInstaller).
# En macOS genera RetroPerfect.app (doble clic sin ventana de Terminal); en Windows
# y Linux, una carpeta con el ejecutable. En ambos casos deja un zip distribuible.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install --quiet --upgrade pyinstaller
rm -rf build dist

if [[ "$(uname -s)" == "Darwin" ]]; then
  nicegui-pack --onedir --windowed --name RetroPerfect scripts/retroperfect_app.py
  mkdir -p dist/RetroPerfect-macos
  mv dist/RetroPerfect.app dist/RetroPerfect-macos/
  cp packaging/LEEME-macOS.txt dist/RetroPerfect-macos/
  # ditto preserva symlinks, permisos y la firma ad-hoc del bundle;
  # un zip normal los aplana y macOS rechaza la app por firma rota.
  ditto -c -k --sequesterRsrc --keepParent dist/RetroPerfect-macos dist/RetroPerfect-macos.zip
  echo "Generados dist/RetroPerfect-macos/RetroPerfect.app y dist/RetroPerfect-macos.zip"
else
  nicegui-pack --onedir --name RetroPerfect scripts/retroperfect_app.py
  python -c "import platform, shutil; shutil.make_archive(f'dist/RetroPerfect-{platform.system().lower()}', 'zip', 'dist', 'RetroPerfect')"
  echo "Generados dist/RetroPerfect/ y su zip distribuible"
fi
