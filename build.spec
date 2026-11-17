# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds TradingBotV1.exe"""
from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "trade_command_centre.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "desktop" / "styles_light.qss"), "desktop"),
        (str(ROOT / "desktop" / "styles_dark.qss"), "desktop"),
        (str(ROOT / "installer" / "scripts"), "installer" / "scripts"),
    ],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "shiboken6",
        "MetaTrader5",
        "app_branding",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "tkinter"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TradingBotV1",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico") if (ROOT / "assets" / "icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TradingBotV1",
)
