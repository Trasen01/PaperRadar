from __future__ import annotations

import ctypes
import multiprocessing
import os
import sys
import threading
from pathlib import Path

import uvicorn

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parents[1]
for path in (BACKEND_DIR, PROJECT_ROOT):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

from app import app


def _start_parent_monitor() -> None:
    parent_pid = os.environ.get("PAPERRADAR_PARENT_PID")
    if not parent_pid or os.name != "nt":
        return

    try:
        pid = int(parent_pid)
    except ValueError:
        return

    def wait_for_parent_exit() -> None:
        kernel32 = ctypes.windll.kernel32
        synchronize = 0x00100000
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return
        try:
            kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
        finally:
            kernel32.CloseHandle(handle)
        os._exit(0)

    thread = threading.Thread(target=wait_for_parent_exit, name="paperradar-parent-monitor", daemon=True)
    thread.start()


def main() -> None:
    _start_parent_monitor()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_config=None, access_log=False)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
