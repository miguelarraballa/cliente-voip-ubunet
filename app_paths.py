"""
Rutas de datos del usuario (writable).
En desarrollo apunta al directorio del proyecto.
Empaquetado:
  - macOS → ~/Library/Application Support/UbutelVoIP/
  - Windows → %APPDATA%/UbutelVoIP/
  - Linux   → ~/.local/share/UbutelVoIP/
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    _base = Path.home() / "AppData" / "Roaming"
elif sys.platform == "darwin":
    _base = Path.home() / "Library" / "Application Support"
else:
    _base = Path.home() / ".local" / "share"

USER_DATA_DIR = _base / "UbutelVoIP"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
