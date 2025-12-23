from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import strings
from .db import DBManager
from .time_log import TimeLogDialog


class PomodoroTimer(QFrame):
    """A simple timer for tracking work time on a specific task."""

    timerStopped = Signal(int, str)  # Emits (elapsed_seconds, task_text)

    def __init__(self, task_text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)

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
        font.setPointSize(20)
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
        self.close()


class PomodoroManager:
    """Manages Pomodoro timers and integrates with time log."""

    def __init__(self, db: DBManager, parent_window):
        self._db = db
        self._parent = parent_window
        self._active_timer: Optional[PomodoroTimer] = None

    @staticmethod
    def _seconds_to_logged_hours(elapsed_seconds: int) -> float:
        """Convert elapsed seconds to decimal hours for logging.

        Rules:
        - For very short runs (< 15 minutes), always round up to 0.25h (15 minutes).
        - Otherwise, round to the closest 0.25h (15-minute) increment.
          Halfway cases (e.g., 22.5 minutes) round up.
        """
        if elapsed_seconds < 0:
            elapsed_seconds = 0

        # 15 minutes = 900 seconds
        if elapsed_seconds < 900:
            return 0.25

        quarters = int(math.floor((elapsed_seconds / 900.0) + 0.5))
        return quarters * 0.25

    def start_timer_for_line(self, line_text: str, date_iso: str):
        """
        Start a new timer for the given line of text and embed it into the
        TimeLogWidget in the main window sidebar.
        """
        # Cancel any existing timer first
        self.cancel_timer()

        # The timer lives inside the TimeLogWidget in the sidebar
        time_log_widget = getattr(self._parent, "time_log", None)
        if time_log_widget is None:
            return

        self._active_timer = PomodoroTimer(line_text, time_log_widget)
        self._active_timer.timerStopped.connect(
            lambda seconds, text: self._on_timer_stopped(seconds, text, date_iso)
        )

        # Ask the TimeLogWidget to own and display the widget
        if hasattr(time_log_widget, "show_pomodoro_widget"):
            time_log_widget.show_pomodoro_widget(self._active_timer)
        else:
            # Fallback - just attach it as a child widget
            self._active_timer.setParent(time_log_widget)
            self._active_timer.show()

    def cancel_timer(self):
        """Cancel any running timer without logging and remove it from the sidebar."""
        if not self._active_timer:
            return

        time_log_widget = getattr(self._parent, "time_log", None)
        if time_log_widget is not None and hasattr(
            time_log_widget, "clear_pomodoro_widget"
        ):
            time_log_widget.clear_pomodoro_widget()
        else:
            # Fallback if the widget API doesn't exist
            self._active_timer.setParent(None)

        self._active_timer.deleteLater()
        self._active_timer = None

    def _on_timer_stopped(self, elapsed_seconds: int, task_text: str, date_iso: str):
        """Handle timer stop - open time log dialog with pre-filled data."""
        # Convert seconds to decimal hours, and handle rounding up or down
        hours = self._seconds_to_logged_hours(elapsed_seconds)

        # Ensure minimum of 0.25 hours
        if hours < 0.25:
            hours = 0.25

        # Untoggle the toolbar button without retriggering the slot
        tool_bar = getattr(self._parent, "toolBar", None)
        if tool_bar is not None and hasattr(tool_bar, "actTimer"):
            action = tool_bar.actTimer
            was_blocked = action.blockSignals(True)
            try:
                action.setChecked(False)
            finally:
                action.blockSignals(was_blocked)

        # Remove the embedded widget
        self.cancel_timer()

        # Open time log dialog
        dlg = TimeLogDialog(
            self._db,
            date_iso,
            self._parent,
            True,
            themes=self._parent.themes,
            close_after_add=True,
        )

        # Pre-fill the hours
        dlg.hours_spin.setValue(hours)

        # Pre-fill the note with task text
        dlg.note.setText(task_text)

        # Show the dialog
        dlg.exec()

        time_log_widget = getattr(self._parent, "time_log", None)
        if time_log_widget is not None:
            # Same behaviour as TimeLogWidget._open_dialog/_open_dialog_log_only:
            # reload the summary so the TimeLogWidget in sidebar updates its totals
            time_log_widget._reload_summary()
            if not time_log_widget.toggle_btn.isChecked():
                time_log_widget.summary_label.setText(
                    strings._("time_log_collapsed_hint")
                )
