# UbutelVoIP

A desktop VoIP client for the **Ubutel** service, built with Python. Make and receive SIP calls directly from your computer, with contact management and call history.

## Features

- Outgoing and incoming calls over SIP/UDP
- Incoming call notification (panel + blinking title + ringtone)
- Clean two-way audio (G.711 PCMU/PCMA, no drift)
- Configurable noise gate and echo gate
- Audio input/output device selection
- Contact import from CSV or XML
- Call history (incoming, outgoing, missed)
- SIP and audio settings from the UI (⚙)
- Packaged as a native application (macOS `.app`, Windows `.exe`)

## Requirements

- Python 3.11 or higher
- Dependencies listed below

### Main dependencies

| Package | Version |
|---|---|
| pyVoIP | 1.6.8 |
| customtkinter | 5.2.2 |
| sounddevice | — |
| numpy | — |
| audioop-lts | — |
| python-dotenv | — |

Install everything with:

```bash
pip install pyVoIP==1.6.8 customtkinter sounddevice numpy audioop-lts python-dotenv
```

## Configuration

Copy the example file and fill in your SIP credentials:

```bash
cp .env.example .env
```

Contents of `.env`:

```
SIP_SERVER=ubcloud02.ubutel.eu
SIP_PORT=5060
SIP_USER=ext200212955
SIP_PASSWORD=YOUR_PASSWORD
SIP_DOMAIN=ubcloud02.ubutel.eu
```

You can also configure settings from within the app by clicking the ⚙ button. Values are saved to `~/.voip_settings.json` (development) or `~/Library/Application Support/UbutelVoIP/.voip_settings.json` (packaged app on macOS).

### Optional environment variables

| Variable | Description | Default |
|---|---|---|
| `AUDIO_INPUT` | Partial name of the microphone device | system default |
| `AUDIO_OUTPUT` | Partial name of the speaker device | system default |
| `AUDIO_NOISE_GATE_DBFS` | Noise gate threshold (negative dBFS) | `-40` |

## Running in development

```bash
python main.py
```

## Contacts

Import a contact list from the UI (**Contacts** button). Two formats are supported:

**CSV** — `name` and `extension` columns:
```csv
name,extension
Reception,100
Tech support,101
```

**XML** — any element with `name`/`nombre` and `extension`/`ext` fields.

The app remembers the last imported file and loads it automatically on startup.

## Building the application

### macOS

Requires PyInstaller and the project assets:

```bash
./build_macos.sh
```

Produces `dist/UbutelVoIP.app` (arm64, Apple Silicon). For Intel, rebuild on an Intel machine.

**First run after installing:**

```bash
mkdir -p ~/Library/Application\ Support/UbutelVoIP
cp .env ~/Library/Application\ Support/UbutelVoIP/.env
# Optional — contacts:
cp nombres_extensiones.csv ~/Library/Application\ Support/UbutelVoIP/
open dist/UbutelVoIP.app
```

### Windows

```bat
pyinstaller UbutelVoIP_windows.spec --noconfirm
```

Produces `dist/UbutelVoIP/UbutelVoIP.exe`. Requires `UbutelVoIP.ico` (convert `logo.png` with any ico converter).

### Linux

```bash
pyinstaller UbutelVoIP_linux.spec --noconfirm
```

## Project structure

```
cliente_telefonia/
├── main.py              # Entry point
├── app.py               # GUI (customtkinter)
├── sip_client.py        # SIP client + monkey-patches for pyVoIP
├── audio.py             # Audio stub (not used directly)
├── contacts.py          # Contact management and import
├── call_log.py          # Call history
├── config.py            # Credential loading (.env / .voip_settings.json)
├── app_paths.py         # User data paths (dev vs bundle)
├── .env.example         # Credentials template
├── sample_contacts.csv  # Sample contact list
├── logo.png             # App logo
├── UbutelVoIP.icns      # Icon for macOS
├── UbutelVoIP.spec      # PyInstaller spec — macOS
├── UbutelVoIP_windows.spec  # PyInstaller spec — Windows
├── UbutelVoIP_linux.spec    # PyInstaller spec — Linux
└── build_macos.sh       # Build script for macOS
```

## Version

**v1.0.6** — Miguel Arrabal
