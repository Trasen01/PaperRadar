from __future__ import annotations

import sys
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from paper_radar.utils import APP_ICON_ICO_PATH, ensure_directories, setup_logging

from .main_window import PaperRadarQtWindow
from .styles import QSS


def run() -> int:
    ensure_directories()
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("PaperRadar")
    icon = QIcon(str(APP_ICON_ICO_PATH))
    if not icon.isNull():
        app.setWindowIcon(icon)
    app.setStyleSheet(QSS)
    window = PaperRadarQtWindow()
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()
    return app.exec()
