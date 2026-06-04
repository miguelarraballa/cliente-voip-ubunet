#!/bin/bash
# build_macos.sh — genera UbutelVoIP.app en dist/
set -e

VENV="venv"
DIST="dist"
APP="$DIST/UbutelVoIP.app"

echo "==> Activando venv..."
source "$VENV/bin/activate"

echo "==> Limpiando builds anteriores..."
rm -rf build "$DIST/UbutelVoIP.app" "$DIST/UbutelVoIP"

echo "==> Compilando con PyInstaller..."
pyinstaller UbutelVoIP.spec --noconfirm

if [ ! -d "$APP" ]; then
    echo "ERROR: no se generó $APP"
    exit 1
fi

echo ""
echo "✅  Build completado: $APP"
echo ""
echo "──────────────────────────────────────────────────────────"
echo "  CONFIGURACIÓN INICIAL (solo la primera vez):"
echo ""
echo "  1. Crea la carpeta de datos del usuario:"
echo "     mkdir -p ~/Library/Application\ Support/UbutelVoIP"
echo ""
echo "  2. Copia tu fichero .env con las credenciales SIP:"
echo "     cp .env ~/Library/Application\ Support/UbutelVoIP/.env"
echo ""
echo "  3. (Opcional) Copia la lista de contactos:"
echo "     cp nombres_extensiones.csv ~/Library/Application\ Support/UbutelVoIP/"
echo ""
echo "  4. Abre la app:"
echo "     open $APP"
echo "──────────────────────────────────────────────────────────"
