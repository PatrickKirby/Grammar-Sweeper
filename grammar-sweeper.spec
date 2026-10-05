# -*- mode: python ; coding: utf-8 -*-


import os
import sys

a = Analysis(
    ['app.py'],
    pathex=[],
    # python3.dll is the stable-ABI stub the downloaded Qt libraries load. PyInstaller only bundles it when something
    # it can see needs it, and Qt is no longer bundled, so it is added here.
    binaries=[(os.path.join(sys.base_prefix, 'python3.dll'), '.')],
    datas=[('assets/icon.png', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'numpy', 'PySide6', 'shiboken6', 'PIL'],
    noarchive=False,
    optimize=0,
)

# Qt (PySide6 and shiboken6) is not bundled. The installer downloads it from PyPI into runtime\ beside the
# program, and app.py adds that folder to the import path. Also drop the Pythonwin editor that pywin32 adds.
_DROP = ('pythonwin' + chr(92), 'pythonwin/')
a.binaries = [b for b in a.binaries if not any(s in b[0].lower() for s in _DROP)]
a.datas = [d for d in a.datas if not any(s in d[0].lower() for s in _DROP)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Grammar Sweeper',
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
    icon=['assets\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Grammar Sweeper',
)
