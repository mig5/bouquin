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

    def _is_system_dark(self) -> bool:
        pal = QGuiApplication.palette()
        # Heuristic: dark windows/backgrounds mean dark system theme
        return pal.color(QPalette.Window).lightness() < 128

    def current(self) -> Theme:
        return self._cfg.theme

    def set(self, theme: Theme):
        self._cfg.theme = theme
        self.apply(theme)

    def apply(self, theme: Theme):
        # Resolve "system" into a concrete theme
        resolved = theme
        if theme == Theme.SYSTEM:
            resolved = Theme.DARK if self._is_system_dark() else Theme.LIGHT

        if resolved == Theme.DARK:
            pal = self._dark_palette()
        else:
            pal = self._light_palette()

        # Always use Fusion so palette applies consistently cross-platform
        QApplication.setStyle("Fusion")

        self._app.setPalette(pal)
        self._current = resolved
        self.themeChanged.emit(theme)

    # ----- Palettes -----
    def _dark_palette(self) -> QPalette:
        pal = QPalette()
        base = QColor(35, 35, 35)
        window = QColor(53, 53, 53)
        text = QColor(220, 220, 220)
        disabled = QColor(127, 127, 127)
        focus = QColor(42, 130, 218)

        # Base surfaces
        pal.setColor(QPalette.Window, window)
        pal.setColor(QPalette.Base, base)
        pal.setColor(QPalette.AlternateBase, window)

        # Text
        pal.setColor(QPalette.WindowText, text)
        pal.setColor(QPalette.ToolTipBase, window)
        pal.setColor(QPalette.ToolTipText, text)
        pal.setColor(QPalette.Text, text)
        pal.setColor(QPalette.PlaceholderText, disabled)
        pal.setColor(QPalette.ButtonText, text)

        # Buttons/frames
        pal.setColor(QPalette.Button, window)
        pal.setColor(QPalette.BrightText, QColor(255, 84, 84))

        # Links / selection
        pal.setColor(QPalette.Highlight, focus)
        pal.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
        pal.setColor(QPalette.Link, QColor(Theme.ORANGE_ANCHOR.value))
        pal.setColor(QPalette.LinkVisited, QColor(Theme.ORANGE_ANCHOR_VISITED.value))

        return pal

    def _light_palette(self) -> QPalette:
        pal = QPalette()

        # Base surfaces
        pal.setColor(QPalette.Window, QColor("#ffffff"))
        pal.setColor(QPalette.Base, QColor("#ffffff"))
        pal.setColor(QPalette.AlternateBase, QColor("#f5f5f5"))

        # Text
        pal.setColor(QPalette.WindowText, QColor("#000000"))
        pal.setColor(QPalette.Text, QColor("#000000"))
        pal.setColor(QPalette.ButtonText, QColor("#000000"))

        # Buttons/frames
        pal.setColor(QPalette.Button, QColor("#f0f0f0"))
        pal.setColor(QPalette.Mid, QColor("#9e9e9e"))

        # Links / selection
        pal.setColor(QPalette.Highlight, QColor("#1a73e8"))
        pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        pal.setColor(QPalette.Link, QColor("#1a73e8"))
        pal.setColor(QPalette.LinkVisited, QColor("#6b4ca5"))

        return pal
