from __future__ import annotations

from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton

from . import strings
from .theme import ThemeManager


class LockOverlay(QWidget):
    def __init__(self, parent: QWidget, on_unlock: callable, themes: ThemeManager):
        """
        Widget that 'locks' the screen after a configured idle time.
        """
        super().__init__(parent)
        self.setObjectName("LockOverlay")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setGeometry(parent.rect())

        self._last_dark: bool | None = None

        lay = QVBoxLayout(self)
        lay.addStretch(1)

        msg = QLabel(strings._("lock_overlay_locked_due_to_inactivity"), self)
        msg.setObjectName("lockLabel")
        msg.setAlignment(Qt.AlignCenter)

        self._btn = QPushButton(strings._("lock_overlay_unlock"), self)
        self._btn.setObjectName("unlockButton")
        self._btn.setFixedWidth(200)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setAutoDefault(True)
        self._btn.setDefault(True)
        self._btn.clicked.connect(on_unlock)

        lay.addWidget(msg, 0, Qt.AlignCenter)
        lay.addWidget(self._btn, 0, Qt.AlignCenter)
        lay.addStretch(1)

        themes.register_lock_overlay(self)
        self.hide()

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() in (QEvent.Resize, QEvent.Show):
            self.setGeometry(obj.rect())
        return False

    def showEvent(self, e):
        super().showEvent(e)
        self._btn.setFocus()
