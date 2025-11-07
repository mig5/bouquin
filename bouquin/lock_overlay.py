from __future__ import annotations

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton


class LockOverlay(QWidget):
    def __init__(self, parent: QWidget, on_unlock: callable):
        """
        Widget that 'locks' the screen after a configured idle time.
        """
        super().__init__(parent)
        self.setObjectName("LockOverlay")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setGeometry(parent.rect())

        self._styling = False  # <-- reentrancy guard
        self._last_dark: bool | None = None

        lay = QVBoxLayout(self)
        lay.addStretch(1)

        msg = QLabel("Locked due to inactivity", self)
        msg.setObjectName("lockLabel")
        msg.setAlignment(Qt.AlignCenter)

        self._btn = QPushButton("Unlock", self)
        self._btn.setObjectName("unlockButton")
        self._btn.setFixedWidth(200)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setAutoDefault(True)
        self._btn.setDefault(True)
        self._btn.clicked.connect(on_unlock)

        lay.addWidget(msg, 0, Qt.AlignCenter)
        lay.addWidget(self._btn, 0, Qt.AlignCenter)
        lay.addStretch(1)

        self._apply_overlay_style()
        self.hide()

    def _is_dark(self, pal: QPalette) -> bool:
        """
        Detect if dark mode is in use.
        """
        c = pal.color(QPalette.Window)
        luma = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
        return luma < 0.5

    def _apply_overlay_style(self):
        if self._styling:
            return
        dark = self._is_dark(self.palette())
        if dark == self._last_dark:
            return
        self._styling = True
        try:
            if dark:
                link = self.palette().color(QPalette.Link)
                accent_hex = link.name()  # e.g. "#FFA500"
                r, g, b = link.red(), link.green(), link.blue()

                self.setStyleSheet(
                    f"""
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
                )
            else:
                # (light mode unchanged)
                self.setStyleSheet(
                    """
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
                )
            self._last_dark = dark
        finally:
            self._styling = False

    def changeEvent(self, ev):
        super().changeEvent(ev)
        # Only re-style on palette flips (user changed theme)
        if ev.type() in (QEvent.PaletteChange, QEvent.ApplicationPaletteChange):
            self._apply_overlay_style()

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() in (QEvent.Resize, QEvent.Show):
            self.setGeometry(obj.rect())
        return False

    def showEvent(self, e):
        super().showEvent(e)
        self._btn.setFocus()
