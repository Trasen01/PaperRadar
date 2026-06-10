from __future__ import annotations

import os
import sys
from pathlib import Path


_dll_directory_handles = []


def _add_dll_dir(path: Path) -> None:
    if not path.exists():
        return
    try:
        _dll_directory_handles.append(os.add_dll_directory(str(path)))
    except (AttributeError, OSError):
        os.environ["PATH"] = str(path) + os.pathsep + os.environ.get("PATH", "")


base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))

for relative in ("", "PySide6", "shiboken6"):
    _add_dll_dir(base / relative)
