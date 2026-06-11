from __future__ import annotations

import sys

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .cache_manager import enforce_cache_limit
from .main_window import MainWindow
from .profile_manager import initialize_profile_system
from .settings import load_settings
from .utils import APP_ICON_PATH, USER_DATA_DIR, ensure_directories, migrate_legacy_data_if_needed, setup_logging
from .version import __version__


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
        import logging

        logging.getLogger(__name__).warning("Cache cleanup failed during startup", exc_info=True)
    first_run_needed = initialize_profile_system()
    app = QApplication(sys.argv)
    app.setApplicationName("PaperRadar")
    app.setApplicationDisplayName("PaperRadar")
    app.setApplicationVersion(__version__)
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    lock = QLockFile(str(USER_DATA_DIR / "PaperRadar.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "PaperRadar", "PaperRadar 已在运行。")
        return 0
    app._single_instance_lock = lock  # Keep the lock alive for the process lifetime.
    app.setQuitOnLastWindowClosed(True)
    window = MainWindow(first_run_needed=first_run_needed)
    window.show()
    return app.exec()
