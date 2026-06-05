# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — UbutelVoIP.app para macOS
Genera un .app bundle en dist/UbutelVoIP.app
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── Assets ──────────────────────────────────────────────────────────────────
ctk_datas    = collect_data_files("customtkinter")
pyvoip_datas = collect_data_files("pyVoIP")

# PortAudio dylib que necesita sounddevice
portaudio = ("venv/lib/python3.13/site-packages/_sounddevice_data",
             "_sounddevice_data")

# ── Hidden imports ───────────────────────────────────────────────────────────
hidden = (
    collect_submodules("pyVoIP")
    + collect_submodules("audioop")   # audioop-lts (stdlib eliminado en 3.13)
    + [
        "sounddevice", "_sounddevice",
        "numpy", "numpy.core", "numpy.core._multiarray_umath",
        "customtkinter",
        "tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox",
        "_tkinter",
        "dotenv",
        "csv", "xml.etree.ElementTree",
        "struct", "audioop",
    ]
)

# ── Analysis ─────────────────────────────────────────────────────────────────
a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=ctk_datas + pyvoip_datas + [portaudio],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "PIL", "scipy", "pandas", "test", "unittest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="UbutelVoIP",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="UbutelVoIP.icns",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="UbutelVoIP",
)

app = BUNDLE(
    coll,
    name="UbutelVoIP.app",
    icon="UbutelVoIP.icns",
    bundle_identifier="eu.ubutel.voip",
    info_plist={
        "CFBundleName":             "UbutelVoIP",
        "CFBundleDisplayName":      "Ubutel VoIP",
        "CFBundleVersion":          "1.0.0",
        "CFBundleShortVersionString": "1.0",
        "NSHighResolutionCapable":  True,
        "NSMicrophoneUsageDescription":
            "UbutelVoIP necesita el micrófono para las llamadas de voz.",
        "LSMinimumSystemVersion":   "12.0",
        "NSRequiresAquaSystemAppearance": False,  # soporte Dark Mode
    },
)
