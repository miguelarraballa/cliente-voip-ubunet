from dotenv import load_dotenv
import os

load_dotenv()

SIP_SERVER = os.getenv("SIP_SERVER", "ubcloud02.ubutel.eu")
SIP_PORT = int(os.getenv("SIP_PORT", "5060"))
SIP_USER = os.getenv("SIP_USER", "ext200212955")
SIP_PASSWORD = os.getenv("SIP_PASSWORD", "")
SIP_DOMAIN = os.getenv("SIP_DOMAIN", "ubcloud02.ubutel.eu")
AUDIO_INPUT  = os.getenv("AUDIO_INPUT", "")   # micro: nombre parcial, vacío = por defecto
AUDIO_OUTPUT = os.getenv("AUDIO_OUTPUT", "")  # altavoz: nombre parcial, vacío = por defecto
