# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['scipy._cyutility']
hiddenimports += collect_submodules('scipy._lib')


a = Analysis(
    ['spectro_stego_app.py'],
    pathex=[],
    binaries=[],
    datas=[('icon/icon.png', 'icon')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'torchaudio', 'triton', 'sympy', 'networkx', 'matplotlib', 'tkinter', 'PyQt5.QtWebEngineCore', 'PyQt5.QtWebEngine', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtQml', 'PyQt5.QtQuick', 'PyQt5.QtQuickWidgets', 'PyQt5.QtNetwork', 'PyQt5.QtMultimedia', 'PyQt5.QtMultimediaWidgets', 'PyQt5.QtBluetooth', 'PyQt5.QtPositioning', 'PyQt5.QtSql', 'PyQt5.QtXml', 'PyQt5.QtPrintSupport', 'PyQt5.QtTest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SpectroStego',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon/icon.ico'],
)
