from __future__ import annotations

import logging
import msvcrt
from pathlib import Path
from tkinter import messagebox

from .cache_manager import enforce_cache_limit
from .profile_manager import initialize_profile_system
from .settings import load_settings
from .tk_window import MainWindow
from .utils import USER_DATA_DIR, ensure_directories, migrate_legacy_data_if_needed, setup_logging


class SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            self.handle.close()
            self.handle = None
            return False

    def release(self) -> None:
        if not self.handle:
            return
        try:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.handle.close()
            self.handle = None


def main() -> int:
    ensure_directories()
    migrate_legacy_data_if_needed()
    setup_logging()
    try:
        settings = load_settings()
        cache_settings = settings.get("cache", {})
        if cache_settings.get("enabled", True):
            enforce_cache_limit(float(cache_settings.get("max_size_gb", 10)))
    except Exception:
        logging.getLogger(__name__).warning("Cache cleanup failed during startup", exc_info=True)

    lock = SingleInstanceLock(USER_DATA_DIR / "PaperRadar.lock")
    if not lock.acquire():
        messagebox.showinfo("PaperRadar", "PaperRadar 已在运行。")
        return 0

    first_run_needed = initialize_profile_system()
    window = MainWindow(first_run_needed=first_run_needed)
    try:
        window.mainloop()
    finally:
        lock.release()
    return 0
