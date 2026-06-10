from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _prepare_qt_dll_paths() -> None:
    if not sys.platform.startswith("win") or not hasattr(os, "add_dll_directory"):
        return

    candidates = [Path(sys.prefix) / "Library" / "bin"]
    for package_name in ("PySide6", "shiboken6"):
        spec = importlib.util.find_spec(package_name)
        if spec and spec.submodule_search_locations:
            package_dir = Path(next(iter(spec.submodule_search_locations)))
            candidates.append(package_dir)
            candidates.append(package_dir / "lib")

    for path in candidates:
        if path.exists():
            os.add_dll_directory(str(path))


_prepare_qt_dll_paths()

from optical_radar.app import main


if __name__ == "__main__":
    main()
