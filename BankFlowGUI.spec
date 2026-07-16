# -*- mode: python ; coding: utf-8 -*-

from datetime import datetime
from pathlib import Path
import subprocess


root = Path.cwd()
version_dir = root / 'build'
version_dir.mkdir(parents=True, exist_ok=True)
version_file = version_dir / 'BankFlowGUI_版本信息.txt'


def git_output(*args):
    try:
        return subprocess.check_output(['git', '-C', str(root), *args], text=True, encoding='utf-8').strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


version_file.write_text(
    '\n'.join([
        '包名称：银行流水识别',
        '包用途：独立流水识别和收入佐证 JSON 草稿导出',
        f'打包时间：{datetime.now():%Y-%m-%d %H:%M:%S}',
        f'Git提交：{git_output("rev-parse", "--short", "HEAD") or "unknown"}',
        f'包含未提交改动：{"是" if git_output("status", "--porcelain") else "否"}',
        '说明：不生成车贷调查报告或收入佐证 Word，详见 RELEASE_MANIFEST.md。',
    ]) + '\n',
    encoding='utf-8',
)

a = Analysis(
    ['gui_v2.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('RELEASE_MANIFEST.md', '.'),
        (str(version_file), '.'),
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
