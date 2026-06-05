# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — UbutelVoIP.exe para Windows
Genera dist\UbutelVoIP\UbutelVoIP.exe (modo onedir)
Run from the project root with:
    pyinstaller UbutelVoIP_windows.spec --noconfirm
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── Assets ──────────────────────────────────────────────────────────────────
ctk_datas    = collect_data_files("customtkinter")
pyvoip_datas = collect_data_files("pyVoIP")

# PortAudio DLL que necesita sounddevice (ruta en Windows)
portaudio = (
    "venv\\Lib\\site-packages\\_sounddevice_data",
    "_sounddevice_data",
)

# ── Hidden imports ───────────────────────────────────────────────────────────
hidden = (
    collect_submodules("pyVoIP")
    + collect_submodules("audioop")
    + [
        "sounddevice", "_sounddevice",
        "numpy", "numpy.core", "numpy.core._multiarray_umath",
        "customtkinter",
        "tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox",
        "_tkinter",
        "dotenv",
        "csv", "xml.etree.ElementTree",
        "struct", "audioop",
        "winsound",
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
    upx=True,
    console=False,
    icon="UbutelVoIP.ico",   # necesitas convertir logo.png → UbutelVoIP.ico
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="UbutelVoIP",
)
