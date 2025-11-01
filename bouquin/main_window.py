from __future__ import annotations

import sys

from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtGui import (
    QAction,
    QFont,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QCalendarWidget,
    QDialog,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .db import DBManager
from .editor import Editor
from .key_prompt import KeyPrompt
from .settings import APP_NAME, load_db_config, save_db_config
from .settings_dialog import SettingsDialog
from .toolbar import ToolBar


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 650)

        self.cfg = load_db_config()
        # Always prompt for the key (we never store it)
        if not self._prompt_for_key_until_valid():
            sys.exit(1)

        # ---- UI: Left fixed panel (calendar) + right editor -----------------
        self.calendar = QCalendarWidget()
        self.calendar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.calendar.setGridVisible(True)
        self.calendar.selectionChanged.connect(self._on_date_changed)

        # Lock the calendar to the left panel at the top to stop it stretching
        # when the main window is resized.
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.addWidget(self.calendar, alignment=Qt.AlignTop)
        left_layout.addStretch(1)
        left_panel.setFixedWidth(self.calendar.sizeHint().width() + 16)

        # This is the note-taking editor
        self.editor = Editor()

        # Toolbar for controlling styling
        tb = ToolBar()
        self.addToolBar(tb)
        # Wire toolbar intents to editor methods
        tb.boldRequested.connect(self.editor.apply_weight)
        tb.italicRequested.connect(self.editor.apply_italic)
        tb.underlineRequested.connect(self.editor.apply_underline)
        tb.strikeRequested.connect(self.editor.apply_strikethrough)
        tb.codeRequested.connect(self.editor.apply_code)
        tb.headingRequested.connect(self.editor.apply_heading)
        tb.bulletsRequested.connect(self.editor.toggle_bullets)
        tb.numbersRequested.connect(self.editor.toggle_numbers)
        tb.alignRequested.connect(self.editor.setAlignment)

        split = QSplitter()
        split.addWidget(left_panel)
        split.addWidget(self.editor)
        split.setStretchFactor(1, 1)  # editor grows

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.addWidget(split)
        self.setCentralWidget(container)

        # Status bar for feedback
        self.statusBar().showMessage("Ready", 800)

        # Menu bar (File)
        mb = self.menuBar()
        file_menu = mb.addMenu("&Application")
        act_save = QAction("&Save", self)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(lambda: self._save_current(explicit=True))
        file_menu.addAction(act_save)
        act_settings = QAction("S&ettings", self)
        act_settings.setShortcut("Ctrl+E")
        act_settings.triggered.connect(self._open_settings)
        file_menu.addAction(act_settings)
        file_menu.addSeparator()
        act_quit = QAction("&Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        # Navigate menu with next/previous/today
        nav_menu = mb.addMenu("&Navigate")
        act_prev = QAction("Previous Day", self)
        act_prev.setShortcut("Ctrl+P")
        act_prev.setShortcutContext(Qt.ApplicationShortcut)
        act_prev.triggered.connect(lambda: self._adjust_day(-1))
        nav_menu.addAction(act_prev)
        self.addAction(act_prev)

        act_next = QAction("Next Day", self)
        act_next.setShortcut("Ctrl+N")
        act_next.setShortcutContext(Qt.ApplicationShortcut)
        act_next.triggered.connect(lambda: self._adjust_day(1))
        nav_menu.addAction(act_next)
        self.addAction(act_next)

        act_today = QAction("Today", self)
        act_today.setShortcut("Ctrl+T")
        act_today.setShortcutContext(Qt.ApplicationShortcut)
        act_today.triggered.connect(self._adjust_today)
        nav_menu.addAction(act_today)
        self.addAction(act_today)

        # Autosave
        self._dirty = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_current)
        self.editor.textChanged.connect(self._on_text_changed)

        # First load + mark dates in calendar with content
        self._load_selected_date()
        self._refresh_calendar_marks()

    def _try_connect(self) -> bool:
        """
        Try to connect to the database.
        """
        try:
            self.db = DBManager(self.cfg)
            ok = self.db.connect()
        except Exception as e:
            if str(e) == "file is not a database":
                error = "The key is probably incorrect."
            else:
                error = str(e)
            QMessageBox.critical(self, "Database Error", error)
            return False
        return ok

    def _prompt_for_key_until_valid(self) -> bool:
        """
        Prompt for the SQLCipher key.
        """
        while True:
            dlg = KeyPrompt(self, message="Enter a key to unlock the notebook")
            if dlg.exec() != QDialog.Accepted:
                return False
            self.cfg.key = dlg.key()
            if self._try_connect():
                return True

    def _refresh_calendar_marks(self):
        """
        Sets a bold marker on the day to indicate that text exists
        for that day.
        """
        fmt_bold = QTextCharFormat()
        fmt_bold.setFontWeight(QFont.Weight.Bold)
        # Clear previous marks
        for d in getattr(self, "_marked_dates", set()):
            self.calendar.setDateTextFormat(d, QTextCharFormat())
        self._marked_dates = set()
        try:
            for date_iso in self.db.dates_with_content():
                qd = QDate.fromString(date_iso, "yyyy-MM-dd")
                if qd.isValid():
                    self.calendar.setDateTextFormat(qd, fmt_bold)
                    self._marked_dates.add(qd)
        except Exception:
            pass

    # --- UI handlers ---------------------------------------------------------
    def _current_date_iso(self) -> str:
        d = self.calendar.selectedDate()
        return f"{d.year():04d}-{d.month():02d}-{d.day():02d}"

    def _load_selected_date(self):
        date_iso = self._current_date_iso()
        try:
            text = self.db.get_entry(date_iso)
        except Exception as e:
            QMessageBox.critical(self, "Read Error", str(e))
            return
        self.editor.blockSignals(True)
        self.editor.setHtml(text)
        self.editor.blockSignals(False)
        self._dirty = False
        # track which date the editor currently represents
        self._active_date_iso = date_iso

    def _on_text_changed(self):
        self._dirty = True
        self._save_timer.start(1200)  # autosave after idle

    def _adjust_day(self, delta: int):
        """Move selection by delta days (negative for previous)."""
        d = self.calendar.selectedDate().addDays(delta)
        self.calendar.setSelectedDate(d)

    def _adjust_today(self):
        """Jump to today."""
        today = QDate.currentDate()
        self.calendar.setSelectedDate(today)

    def _on_date_changed(self):
        """
        When the calendar selection changes, save the previous day's note if dirty,
        so we don't lose that text, then load the newly selected day.
        """
        # Stop pending autosave and persist current buffer if needed
        try:
            self._save_timer.stop()
        except Exception:
            pass
        prev = getattr(self, "_active_date_iso", None)
        if prev and self._dirty:
            self._save_date(prev, explicit=False)
        # Now load the newly selected date
        self._load_selected_date()

    def _save_date(self, date_iso: str, explicit: bool = False):
        """
        Save editor contents into the given date. Shows status on success.
        explicit=True means user invoked Save: show feedback even if nothing changed.
        """
        if not self._dirty and not explicit:
            return
        text = self.editor.toHtml()
        try:
            self.db.upsert_entry(date_iso, text)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))
            return
        self._dirty = False
        self._refresh_calendar_marks()
        # Feedback in the status bar
        from datetime import datetime as _dt

        self.statusBar().showMessage(
            f"Saved {date_iso} at {_dt.now().strftime('%H:%M:%S')}", 2000
        )

    def _save_current(self, explicit: bool = False):
        # Delegate to _save_date for the currently selected date
        self._save_date(self._current_date_iso(), explicit)

    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self.db, self)
        if dlg.exec() == QDialog.Accepted:
            new_cfg = dlg.config
            if new_cfg.path != self.cfg.path:
                # Save the new path to the notebook
                self.cfg.path = new_cfg.path
                save_db_config(self.cfg)
                self.db.close()
                # Prompt again for the key for the new path
                if not self._prompt_for_key_until_valid():
                    QMessageBox.warning(
                        self, "Reopen failed", "Could not unlock database at new path."
                    )
                    return
                self._load_selected_date()
                self._refresh_calendar_marks()

    def closeEvent(self, event):
        try:
            self._save_current()
            self.db.close()
        except Exception:
            pass
        super().closeEvent(event)
