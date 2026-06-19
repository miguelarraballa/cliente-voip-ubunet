# UbutelVoIP

Cliente VoIP de escritorio para el servicio **Ubutel**, construido con Python. Permite realizar y recibir llamadas SIP directamente desde el ordenador, con gestión de contactos e historial de llamadas.

## Características

- Llamadas salientes y entrantes sobre SIP/UDP
- Notificación de llamada entrante (panel + título parpadeante + sonido)
- Audio bidireccional limpio (G.711 PCMU/PCMA, sin drift)
- Noise gate y echo gate configurables
- Selección de dispositivo de entrada/salida de audio
- Importación de contactos desde CSV o XML
- Historial de llamadas (entrantes, salientes, perdidas)
- Configuración SIP y audio desde la interfaz (⚙)
- Empaquetado como aplicación nativa (macOS `.app`, Windows `.exe`)

## Requisitos

- Python 3.11 o superior
- Las dependencias listadas a continuación

### Dependencias principales

| Paquete | Versión |
|---|---|
| pyVoIP | 1.6.8 |
| customtkinter | 5.2.2 |
| sounddevice | — |
| numpy | — |
| audioop-lts | — |
| python-dotenv | — |

Instalar todo con:

```bash
pip install pyVoIP==1.6.8 customtkinter sounddevice numpy audioop-lts python-dotenv
```

## Configuración

Copia el fichero de ejemplo y rellena tus credenciales SIP:

```bash
cp .env.example .env
```

Contenido de `.env`:

```
SIP_SERVER=ubcloud02.ubutel.eu
SIP_PORT=5060
SIP_USER=ext200212955
SIP_PASSWORD=TU_CONTRASEÑA
SIP_DOMAIN=ubcloud02.ubutel.eu
```

También puedes configurar los ajustes desde la propia aplicación pulsando el botón ⚙. Los valores se guardan en `~/.voip_settings.json` (desarrollo) o en `~/Library/Application Support/UbutelVoIP/.voip_settings.json` (app empaquetada en macOS).

### Variables de entorno opcionales

| Variable | Descripción | Por defecto |
|---|---|---|
| `AUDIO_INPUT` | Nombre parcial del micrófono | dispositivo del sistema |
| `AUDIO_OUTPUT` | Nombre parcial del altavoz | dispositivo del sistema |
| `AUDIO_NOISE_GATE_DBFS` | Umbral del noise gate (dBFS negativo) | `-40` |

## Ejecución en desarrollo

```bash
python main.py
```

## Contactos

Puedes importar una lista de contactos desde la interfaz (botón **Contactos**). Se aceptan dos formatos:

**CSV** — columnas `name` y `extension`:
```csv
name,extension
Recepción,100
Soporte técnico,101
```

**XML** — cualquier elemento con campos `name`/`nombre` y `extension`/`ext`.

La app recuerda el último archivo importado y lo carga automáticamente al arrancar.

## Compilar la aplicación

### macOS

Requiere PyInstaller y los recursos del proyecto:

```bash
./build_macos.sh
```

Genera `dist/UbutelVoIP.app` (arm64, Apple Silicon). Para Intel, recompilar en máquina Intel.

**Primera ejecución tras instalar:**

```bash
mkdir -p ~/Library/Application\ Support/UbutelVoIP
cp .env ~/Library/Application\ Support/UbutelVoIP/.env
# Opcional — contactos:
cp nombres_extensiones.csv ~/Library/Application\ Support/UbutelVoIP/
open dist/UbutelVoIP.app
```

### Windows

```bat
pyinstaller UbutelVoIP_windows.spec --noconfirm
```

Genera `dist/UbutelVoIP/UbutelVoIP.exe`. Requiere `UbutelVoIP.ico` (convierte `logo.png` con cualquier conversor ico).

### Linux

```bash
pyinstaller UbutelVoIP_linux.spec --noconfirm
```

## Estructura del proyecto

```
cliente_telefonia/
├── main.py              # Entry point
├── app.py               # Interfaz gráfica (customtkinter)
├── sip_client.py        # Cliente SIP + monkey-patches para pyVoIP
├── audio.py             # Stub de audio (no usado directamente)
├── contacts.py          # Gestión e importación de contactos
├── call_log.py          # Historial de llamadas
├── config.py            # Carga de credenciales (.env / .voip_settings.json)
├── app_paths.py         # Rutas de datos de usuario (dev vs bundle)
├── .env.example         # Plantilla de credenciales
├── sample_contacts.csv  # Ejemplo de lista de contactos
├── logo.png             # Logo de la app
├── UbutelVoIP.icns      # Icono para macOS
├── UbutelVoIP.spec      # Spec PyInstaller — macOS
├── UbutelVoIP_windows.spec  # Spec PyInstaller — Windows
├── UbutelVoIP_linux.spec    # Spec PyInstaller — Linux
└── build_macos.sh       # Script de build para macOS
```

## Versión

**v1.0.6** — Miguel Arrabal
