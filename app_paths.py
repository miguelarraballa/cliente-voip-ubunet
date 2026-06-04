"""
Rutas de datos del usuario (writable).
En desarrollo apunta al directorio del proyecto.
Empaquetado como .app apunta a ~/Library/Application Support/UbutelVoIP/.
"""
import sys
from pathlib import Path

_frozen = getattr(sys, "frozen", False)

if _frozen:
    USER_DATA_DIR = Path.home() / "Library" / "Application Support" / "UbutelVoIP"
else:
    USER_DATA_DIR = Path(__file__).parent

USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
