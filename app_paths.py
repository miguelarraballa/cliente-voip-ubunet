"""
Rutas de datos del usuario (writable).
En desarrollo apunta al directorio del proyecto.
Empaquetado como .app apunta a ~/Library/Application Support/UbutelVoIP/.
"""
from pathlib import Path

USER_DATA_DIR = Path.home() / "Library" / "Application Support" / "UbutelVoIP"

USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
