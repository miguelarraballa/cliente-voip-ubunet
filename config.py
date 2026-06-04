from dotenv import load_dotenv
import os
from pathlib import Path
from app_paths import USER_DATA_DIR

# Buscar .env en la carpeta de datos del usuario primero, luego junto al script
_env = USER_DATA_DIR / ".env"
if not _env.exists():
    _env = Path(__file__).parent / ".env"
load_dotenv(_env)

SIP_SERVER = os.getenv("SIP_SERVER", "ubcloud02.ubutel.eu")
SIP_PORT = int(os.getenv("SIP_PORT", "5060"))
SIP_USER = os.getenv("SIP_USER", "ext200212955")
SIP_PASSWORD = os.getenv("SIP_PASSWORD", "")
SIP_DOMAIN = os.getenv("SIP_DOMAIN", "ubcloud02.ubutel.eu")
AUDIO_INPUT  = os.getenv("AUDIO_INPUT", "")   # micro: nombre parcial, vacío = por defecto
AUDIO_OUTPUT = os.getenv("AUDIO_OUTPUT", "")  # altavoz: nombre parcial, vacío = por defecto
# Umbral del noise gate en dBFS (negativo). El micro se silencia cuando el nivel
# cae por debajo de este umbral. -40 filtra hiss/eco residual de auriculares.
# Subir hacia 0 para cortar más ruido (ej: -35 o -30 para micros muy sensibles).
AUDIO_NOISE_GATE_DBFS = float(os.getenv("AUDIO_NOISE_GATE_DBFS", "-40"))
