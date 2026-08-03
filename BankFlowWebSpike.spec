# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

repo = Path(SPECPATH)

a = Analysis(
    [str(repo / "gui_web_spike_app.py")],
    pathex=[str(repo)],
    binaries=[],
    datas=[(str(repo / "web_frontend" / "dist"), "web_frontend/dist")],
    hiddenimports=[
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebChannel",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BankFlowWebSpike",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BankFlowWebSpike",
)
