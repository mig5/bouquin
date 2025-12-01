from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from . import strings
from .db import DBManager
from .time_log import TimeLogDialog


class PomodoroTimer(QDialog):
    """A simple timer dialog for tracking work time on a specific task."""

    timerStopped = Signal(int, str)  # Emits (elapsed_seconds, task_text)

    def __init__(self, task_text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(strings._("toolbar_pomodoro_timer"))
        self.setModal(False)
        self.setMinimumWidth(300)

        self._task_text = task_text
        self._elapsed_seconds = 0
        self._running = False

        layout = QVBoxLayout(self)

        # Task label
        task_label = QLabel(task_text)
        task_label.setWordWrap(True)
        layout.addWidget(task_label)

        # Timer display
        self.time_label = QLabel("00:00:00")
        font = self.time_label.font()
        font.setPointSize(24)
        font.setBold(True)
        self.time_label.setFont(font)
        self.time_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.time_label)

        # Control buttons
        btn_layout = QHBoxLayout()

        self.start_pause_btn = QPushButton(strings._("start"))
        self.start_pause_btn.clicked.connect(self._toggle_timer)
        btn_layout.addWidget(self.start_pause_btn)

        self.stop_btn = QPushButton(strings._("stop_and_log"))
        self.stop_btn.clicked.connect(self._stop_and_log)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)

        layout.addLayout(btn_layout)

        # Internal timer (ticks every second)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    @Slot()
    def _toggle_timer(self):
        """Start or pause the timer."""
        if self._running:
            # Pause
            self._running = False
            self._timer.stop()
            self.start_pause_btn.setText(strings._("resume"))
        else:
            # Start/Resume
            self._running = True
            self._timer.start(1000)  # 1 second
            self.start_pause_btn.setText(strings._("pause"))
            self.stop_btn.setEnabled(True)

    @Slot()
    def _tick(self):
        """Update the elapsed time display."""
        self._elapsed_seconds += 1
        self._update_display()

    def _update_display(self):
        """Update the time display label."""
        hours = self._elapsed_seconds // 3600
        minutes = (self._elapsed_seconds % 3600) // 60
        seconds = self._elapsed_seconds % 60
        self.time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    @Slot()
    def _stop_and_log(self):
        """Stop the timer and emit signal to open time log."""
        if self._running:
            self._running = False
            self._timer.stop()

        self.timerStopped.emit(self._elapsed_seconds, self._task_text)
        self.accept()


class PomodoroManager:
    """Manages Pomodoro timers and integrates with time log."""

    def __init__(self, db: DBManager, parent_window):
        self._db = db
        self._parent = parent_window
        self._active_timer: Optional[PomodoroTimer] = None

    def start_timer_for_line(self, line_text: str, date_iso: str):
        """Start a new timer for the given line of text."""
        # Stop any existing timer
        if self._active_timer and self._active_timer.isVisible():
            self._active_timer.close()

        # Create new timer
        self._active_timer = PomodoroTimer(line_text, self._parent)
        self._active_timer.timerStopped.connect(
            lambda seconds, text: self._on_timer_stopped(seconds, text, date_iso)
        )
        self._active_timer.show()

    def _on_timer_stopped(self, elapsed_seconds: int, task_text: str, date_iso: str):
        """Handle timer stop - open time log dialog with pre-filled data."""
        # Convert seconds to decimal hours, rounding up to the nearest 0.25 hour (15 minutes)
        quarter_hours = math.ceil(elapsed_seconds / 900)
        hours = quarter_hours * 0.25

        # Ensure minimum of 0.25 hours
        if hours < 0.25:
            hours = 0.25

        # Open time log dialog
        dlg = TimeLogDialog(
            self._db, date_iso, self._parent, True, themes=self._parent.themes
        )

        # Pre-fill the hours
        dlg.hours_spin.setValue(hours)

        # Pre-fill the note with task text
        dlg.note.setText(task_text)

        # Show the dialog
        dlg.exec()
