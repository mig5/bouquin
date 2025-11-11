from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from PySide6.QtGui import QPalette, QColor, QGuiApplication
from PySide6.QtWidgets import QApplication, QCalendarWidget, QWidget
from PySide6.QtCore import QObject, Signal
from weakref import WeakSet


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
        self._current = None
        self._calendars: "WeakSet[QCalendarWidget]" = WeakSet()
        self._lock_overlays: "WeakSet[QWidget]" = WeakSet()

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

    def _restyle_registered(self) -> None:
        for cal in list(self._calendars):
            if cal is not None:
                self._apply_calendar_theme(cal)

        for overlay in list(self._lock_overlays):
            if overlay is not None:
                self._apply_lock_overlay_theme(overlay)

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
        # Re-style any registered widgets
        self._restyle_registered()
        self.themeChanged.emit(self._current)

    def register_calendar(self, cal: QCalendarWidget) -> None:
        """Start theming calendar and keep it in sync with theme changes."""
        self._calendars.add(cal)
        self._apply_calendar_theme(cal)

    def register_lock_overlay(self, overlay: QWidget) -> None:
        """Start theming lock overlay and keep it in sync with theme changes."""
        self._lock_overlays.add(overlay)
        self._apply_lock_overlay_theme(overlay)

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

    def _apply_calendar_theme(self, cal: QCalendarWidget) -> None:
        """Use orange accents on the calendar in dark mode only."""
        app_pal = QApplication.instance().palette()
        is_dark = (self.current() == Theme.DARK) or (
            self.current() == Theme.SYSTEM and self._is_system_dark()
        )

        if is_dark:
            highlight_css = Theme.ORANGE_ANCHOR.value
            highlight = QColor(highlight_css)
            black = QColor(0, 0, 0)

            # Per-widget palette: selection color inside the date grid
            pal = cal.palette()
            pal.setColor(QPalette.Highlight, highlight)
            pal.setColor(QPalette.HighlightedText, black)
            cal.setPalette(pal)

            # Stylesheet: nav bar + selected-day background
            cal.setStyleSheet(self._calendar_qss(highlight_css))
        else:
            # Back to app defaults in light/system-light
            cal.setPalette(app_pal)
            cal.setStyleSheet("")

        cal.update()

    def _calendar_qss(self, highlight_css: str) -> str:
        return f"""
        QWidget#qt_calendar_navigationbar {{ background-color: {highlight_css}; }}
        QCalendarWidget QToolButton {{ color: black; }}
        QCalendarWidget QToolButton:hover {{ background-color: rgba(255,165,0,0.20); }}
        /* Selected day color in the table view */
        QCalendarWidget QTableView:enabled {{
            selection-background-color: {highlight_css};
            selection-color: black;
        }}
        /* Keep weekday header readable */
        QCalendarWidget QTableView QHeaderView::section {{
            background: transparent;
            color: palette(windowText);
        }}
        """

    def _apply_lock_overlay_theme(self, overlay: QWidget) -> None:
        """
        Style the LockOverlay (objectName 'LockOverlay') using theme colors.
        Dark: opaque black bg, orange accent; Light: translucent scrim, palette-driven colors.
        """
        pal = QApplication.instance().palette()
        is_dark = (self.current() == Theme.DARK) or (
            self.current() == Theme.SYSTEM and self._is_system_dark()
        )

        if is_dark:
            # Use the link color as the accent (you set this to ORANGE in dark palette)
            accent = pal.color(QPalette.Link)
            r, g, b = accent.red(), accent.green(), accent.blue()
            accent_hex = accent.name()

            qss = f"""
#LockOverlay {{ background-color: rgb(0,0,0); }}
#LockOverlay QLabel#lockLabel {{ color: {accent_hex}; font-weight: 600; }}

#LockOverlay QPushButton#unlockButton {{
    color: {accent_hex};
    background-color: rgba({r},{g},{b},0.10);
    border: 1px solid {accent_hex};
    border-radius: 8px;
    padding: 8px 16px;
}}
#LockOverlay QPushButton#unlockButton:hover {{
    background-color: rgba({r},{g},{b},0.16);
    border-color: {accent_hex};
}}
#LockOverlay QPushButton#unlockButton:pressed {{
    background-color: rgba({r},{g},{b},0.24);
}}
#LockOverlay QPushButton#unlockButton:focus {{
    outline: none;
    border-color: {accent_hex};
}}
"""
        else:
            qss = """
#LockOverlay { background-color: rgba(0,0,0,120); }
#LockOverlay QLabel#lockLabel { color: palette(window-text); font-weight: 600; }

#LockOverlay QPushButton#unlockButton {
    color: palette(button-text);
    background-color: rgba(255,255,255,0.92);
    border: 1px solid rgba(0,0,0,0.25);
    border-radius: 8px;
    padding: 8px 16px;
}
#LockOverlay QPushButton#unlockButton:hover {
    background-color: rgba(255,255,255,1.0);
    border-color: rgba(0,0,0,0.35);
}
#LockOverlay QPushButton#unlockButton:pressed {
    background-color: rgba(245,245,245,1.0);
}
#LockOverlay QPushButton#unlockButton:focus {
    outline: none;
    border-color: palette(highlight);
}
"""
        overlay.setStyleSheet(qss)
        overlay.update()
