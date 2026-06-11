from __future__ import annotations

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from .utils import APP_ICON_PATH


class RadarTrayIcon(QSystemTrayIcon):
    def __init__(self, parent, on_show, on_run_now, on_open_reports, on_exit) -> None:
        app = QApplication.instance()
        if APP_ICON_PATH.exists():
            icon = QIcon(str(APP_ICON_PATH))
        else:
            icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon) if app else QIcon()
        super().__init__(icon, parent)

        menu = QMenu()
        show_action = QAction("显示主窗口", menu)
        run_action = QAction("立即检查", menu)
        open_reports_action = QAction("打开报告文件夹", menu)
        exit_action = QAction("退出", menu)

        show_action.triggered.connect(on_show)
        run_action.triggered.connect(on_run_now)
        open_reports_action.triggered.connect(on_open_reports)
        exit_action.triggered.connect(on_exit)

        menu.addAction(show_action)
        menu.addAction(run_action)
        menu.addAction(open_reports_action)
        menu.addSeparator()
        menu.addAction(exit_action)

        self.setContextMenu(menu)
        self.setToolTip("PaperRadar")
        self.activated.connect(
            lambda reason: on_show() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
        )
