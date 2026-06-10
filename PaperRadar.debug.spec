# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all


project_dir = Path.cwd()
pyside6_datas, pyside6_binaries, pyside6_hiddenimports = collect_all("PySide6")
shiboken6_datas, shiboken6_binaries, shiboken6_hiddenimports = collect_all("shiboken6")
library_bin = Path(sys.prefix) / "Library" / "bin"
conda_qt_binaries = []
if library_bin.exists():
    for pattern in (
        "pyside6*.dll",
        "shiboken6*.dll",
        "Qt6*.dll",
        "icu*.dll",
        "MSVCP140*.dll",
        "VCRUNTIME140*.dll",
        "zlib*.dll",
        "libpng*.dll",
        "freetype*.dll",
        "harfbuzz*.dll",
        "brotli*.dll",
        "bz2*.dll",
    ):
        conda_qt_binaries.extend((str(path), ".") for path in library_bin.glob(pattern))

a = Analysis(
    ["run.py"],
    pathex=[str(project_dir)],
    binaries=pyside6_binaries + shiboken6_binaries + conda_qt_binaries,
    datas=[
        ("config", "config"),
        ("assets", "assets"),
    ] + pyside6_datas + shiboken6_datas,
    hiddenimports=pyside6_hiddenimports + shiboken6_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["packaging/pyside6_dll_path.py"],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PaperRadarDebug",
    icon="assets/PaperRadar.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    upx=True,
    upx_exclude=[],
    name="PaperRadarDebug",
)
