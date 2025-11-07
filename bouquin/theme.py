from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from PySide6.QtGui import QPalette, QColor, QGuiApplication
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal


class Theme(Enum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"
    ORANGE_ANCHOR = "#FFA500"
    ORANGE_ANCHOR_VISITED = "#B38000"


@dataclass
class ThemeConfig:
    theme: Theme = Theme.SYSTEM


class ThemeManager(QObject):
    themeChanged = Signal(Theme)

    def __init__(self, app: QApplication, cfg: ThemeConfig):
        super().__init__()
        self._app = app
        self._cfg = cfg

        # Follow OS if supported (Qt 6+)
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(
                lambda _: (self._cfg.theme == Theme.SYSTEM)
                and self.apply(self._cfg.theme)
            )

    def current(self) -> Theme:
        return self._cfg.theme

    def set(self, theme: Theme):
        self._cfg.theme = theme
        self.apply(theme)

    def apply(self, theme: Theme):
        # Resolve "system"
        if theme == Theme.SYSTEM:
            hints = QGuiApplication.styleHints()
            scheme = getattr(hints, "colorScheme", None)
            if callable(scheme):
                scheme = hints.colorScheme()
            # 0=Light, 1=Dark; fall back to Light
            theme = Theme.DARK if scheme == 1 else Theme.LIGHT

        # Always use Fusion so palette applies consistently cross-platform
        self._app.setStyle("Fusion")

        if theme == Theme.DARK:
            pal = self._dark_palette()
            self._app.setPalette(pal)
            self._app.setStyleSheet("")
        else:
            pal = self._light_palette()
            self._app.setPalette(pal)
            self._app.setStyleSheet("")

        self.themeChanged.emit(theme)

    # ----- Palettes -----
    def _dark_palette(self) -> QPalette:
        pal = QPalette()
        base = QColor(35, 35, 35)
        window = QColor(53, 53, 53)
        text = QColor(220, 220, 220)
        disabled = QColor(127, 127, 127)
        focus = QColor(42, 130, 218)

        pal.setColor(QPalette.Window, window)
        pal.setColor(QPalette.WindowText, text)
        pal.setColor(QPalette.Base, base)
        pal.setColor(QPalette.AlternateBase, window)
        pal.setColor(QPalette.ToolTipBase, window)
        pal.setColor(QPalette.ToolTipText, text)
        pal.setColor(QPalette.Text, text)
        pal.setColor(QPalette.PlaceholderText, disabled)
        pal.setColor(QPalette.Button, window)
        pal.setColor(QPalette.ButtonText, text)
        pal.setColor(QPalette.BrightText, QColor(255, 84, 84))
        pal.setColor(QPalette.Highlight, focus)
        pal.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
        pal.setColor(QPalette.Link, QColor(Theme.ORANGE_ANCHOR.value))
        pal.setColor(QPalette.LinkVisited, QColor(Theme.ORANGE_ANCHOR_VISITED.value))

        return pal

    def _light_palette(self) -> QPalette:
        # Let Qt provide its default light palette, but nudge a couple roles
        pal = self._app.style().standardPalette()
        pal.setColor(QPalette.Highlight, QColor(0, 120, 215))
        pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        pal.setColor(
            QPalette.Link, QColor("#1a73e8")
        )  # Light blue for links in light mode
        return pal
