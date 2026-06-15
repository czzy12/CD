# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['gui_v2.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        ('configs', 'configs'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'accelerate',
        'cv2',
        'matplotlib',
        'onnx',
        'onnxruntime',
        'pandas',
        'pypdfium2',
        'rapidocr',
        'scipy',
        'sklearn',
        'tensorflow',
        'torch',
        'torchaudio',
        'torchvision',
        'transformers',
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BankFlowGUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BankFlowGUI',
)
