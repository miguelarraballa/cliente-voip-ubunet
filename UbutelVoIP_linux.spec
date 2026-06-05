# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — UbutelVoIP para Linux
Genera dist/UbutelVoIP/UbutelVoIP (binario ELF, onedir)
Run from the project root with:
    pyinstaller UbutelVoIP_linux.spec --noconfirm
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── Assets ──────────────────────────────────────────────────────────────────
ctk_datas    = collect_data_files("customtkinter")
pyvoip_datas = collect_data_files("pyVoIP")
sd_datas     = collect_data_files("sounddevice")

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
    ]
)

# ── Analysis ─────────────────────────────────────────────────────────────────
a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=ctk_datas + pyvoip_datas + sd_datas,
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
