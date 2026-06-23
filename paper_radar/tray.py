from __future__ import annotations


class RadarTrayIcon:
    """Compatibility stub for the previous PySide6 tray integration."""

    def __init__(self, *args, **kwargs) -> None:
        self.visible = False

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False
