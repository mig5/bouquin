from __future__ import annotations

import datetime
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import (
    QDate,
    QDateTime,
    QEvent,
    QSettings,
    QSignalBlocker,
    Qt,
    QTime,
    QTimer,
    QUrl,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QGuiApplication,
    QKeySequence,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import strings
from .bug_report_dialog import BugReportDialog
from .db import DBManager
from .documents import DocumentsDialog, TodaysDocumentsWidget
from .find_bar import FindBar
from .history_dialog import HistoryDialog
from .key_prompt import KeyPrompt
from .lock_overlay import LockOverlay
from .markdown_editor import MarkdownEditor
from .pomodoro_timer import PomodoroManager
from .reminders import UpcomingRemindersWidget, ReminderWebHook
from .save_dialog import SaveDialog
from .search import Search
from .settings import APP_NAME, APP_ORG, load_db_config, save_db_config
from .settings_dialog import SettingsDialog
from .statistics_dialog import StatisticsDialog
from .tags_widget import PageTagsWidget
from .theme import ThemeManager
from .time_log import TimeLogWidget
from .toolbar import ToolBar
from .version_check import VersionChecker


class MainWindow(QMainWindow):
    def __init__(self, themes: ThemeManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 650)

        self.themes = themes  # Store the themes manager
        self.version_checker = VersionChecker(self)

        self.cfg = load_db_config()
        if not os.path.exists(self.cfg.path):
            # Fresh database/first time use, so guide the user re: setting a key
            first_time = True
        else:
            first_time = False

        # Prompt for the key unless it is found in config
        if not self.cfg.key:
            if not self._prompt_for_key_until_valid(first_time):
                sys.exit(1)
        else:
            self._try_connect()

        self.settings = QSettings(APP_ORG, APP_NAME)

        # ---- UI: Left fixed panel (calendar) + right editor -----------------
        self.calendar = QCalendarWidget()
        self.calendar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.calendar.setGridVisible(True)
        self.calendar.selectionChanged.connect(self._on_date_changed)
        self.themes.register_calendar(self.calendar)

        self.search = Search(self.db)
        self.search.openDateRequested.connect(self._load_selected_date)
        self.search.resultDatesChanged.connect(self._on_search_dates_changed)

        # Features
        self.time_log = TimeLogWidget(self.db, themes=self.themes)

        self.tags = PageTagsWidget(self.db)
        self.tags.tagActivated.connect(self._on_tag_activated)
        self.tags.tagAdded.connect(self._on_tag_added)

        self.upcoming_reminders = UpcomingRemindersWidget(self.db)
        self.upcoming_reminders.reminderTriggered.connect(self._send_reminder_webhook)
        self.upcoming_reminders.reminderTriggered.connect(self._show_flashing_reminder)

        # When invoices change reminders (e.g. invoice paid), refresh the Reminders widget
        self.time_log.remindersChanged.connect(self.upcoming_reminders.refresh)

        self.pomodoro_manager = PomodoroManager(self.db, self)

        # Lock the calendar to the left panel at the top to stop it stretching
        # when the main window is resized.
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.addWidget(self.calendar)
        left_layout.addWidget(self.search)
        left_layout.addWidget(self.upcoming_reminders)
        self.todays_documents = TodaysDocumentsWidget(self.db, self._current_date_iso())
        left_layout.addWidget(self.todays_documents)
        left_layout.addWidget(self.time_log)
        left_layout.addWidget(self.tags)
        left_panel.setFixedWidth(self.calendar.sizeHint().width() + 16)

        # Create tab widget to hold multiple editors
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self._prev_editor = None

        # Toolbar for controlling styling
        self.toolBar = ToolBar()
        self.addToolBar(self.toolBar)
        self._bind_toolbar()

        # Create the first editor tab
        self._create_new_tab()
        self._prev_editor = self.editor

        split = QSplitter()
        split.addWidget(left_panel)
        split.addWidget(self.tab_widget)
        split.setStretchFactor(1, 1)

        # Enable context menu on calendar for opening dates in new tabs
        self.calendar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.calendar.customContextMenuRequested.connect(
            self._show_calendar_context_menu
        )

        # Flag to prevent _on_date_changed when showing context menu
        self._showing_context_menu = False

        # Install event filter to catch right-clicks before selectionChanged fires
        self.calendar.installEventFilter(self)

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.addWidget(split)
        self.setCentralWidget(container)

        # Idle lock setup
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._enter_lock)
        self._apply_idle_minutes(getattr(self.cfg, "idle_minutes", 15))
        self._idle_timer.start()

        # full-window overlay that sits on top of the central widget
        self._lock_overlay = LockOverlay(
            self.centralWidget(), self._on_unlock_clicked, themes=self.themes
        )
        self.centralWidget().installEventFilter(self._lock_overlay)

        self._locked = False

        # reset idle timer on any key press anywhere in the app
        QApplication.instance().installEventFilter(self)

        # Focus on the editor
        self.setFocusPolicy(Qt.StrongFocus)
        self.editor.setFocusPolicy(Qt.StrongFocus)
        self.toolBar.setFocusPolicy(Qt.NoFocus)
        for w in self.toolBar.findChildren(QWidget):
            w.setFocusPolicy(Qt.NoFocus)
        QGuiApplication.instance().applicationStateChanged.connect(
            self._on_app_state_changed
        )

        # Status bar for feedback
        self.statusBar().showMessage(strings._("main_window_ready"), 800)
        # Add findBar and add it to the statusBar
        # FindBar will get the current editor dynamically via a callable
        self.findBar = FindBar(lambda: self.editor, shortcut_parent=self, parent=self)
        self.statusBar().addPermanentWidget(self.findBar)
        # When the findBar closes, put the caret back in the editor
        self.findBar.closed.connect(self._focus_editor_now)

        # Menu bar (File)
        mb = self.menuBar()
        file_menu = mb.addMenu("&" + strings._("file"))
        act_save = QAction("&" + strings._("main_window_save_a_version"), self)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(lambda: self._save_current(explicit=True))
        file_menu.addAction(act_save)
        act_history = QAction("&" + strings._("history"), self)
        act_history.setShortcut("Ctrl+Shift+H")
        act_history.setShortcutContext(Qt.ApplicationShortcut)
        act_history.triggered.connect(self._open_history)
        file_menu.addAction(act_history)
        act_settings = QAction(strings._("main_window_settings_accessible_flag"), self)
        act_settings.setShortcut("Ctrl+Shift+.")
        act_settings.triggered.connect(self._open_settings)
        file_menu.addAction(act_settings)
        act_export = QAction(strings._("export_accessible_flag"), self)
        act_export.setShortcut("Ctrl+Shift+E")
        act_export.triggered.connect(self._export)
        file_menu.addAction(act_export)
        act_backup = QAction("&" + strings._("backup"), self)
        act_backup.setShortcut("Ctrl+Shift+B")
        act_backup.triggered.connect(self._backup)
        file_menu.addAction(act_backup)
        act_stats = QAction(strings._("main_window_statistics_accessible_flag"), self)
        act_stats.setShortcut("Ctrl+Shift+S")
        act_stats.triggered.connect(self._open_statistics)
        file_menu.addAction(act_stats)
        act_lock = QAction(strings._("main_window_lock_screen_accessibility"), self)
        act_lock.setShortcut("Ctrl+Shift+L")
        act_lock.triggered.connect(self._enter_lock)
        file_menu.addAction(act_lock)
        file_menu.addSeparator()
        act_quit = QAction("&" + strings._("quit"), self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        # Navigate menu with next/previous/today
        nav_menu = mb.addMenu("&" + strings._("navigate"))
        act_prev = QAction(strings._("previous_day"), self)
        act_prev.setShortcut("Ctrl+Shift+P")
        act_prev.setShortcutContext(Qt.ApplicationShortcut)
        act_prev.triggered.connect(lambda: self._adjust_day(-1))
        nav_menu.addAction(act_prev)
        self.addAction(act_prev)

        act_next = QAction(strings._("next_day"), self)
        act_next.setShortcut("Ctrl+Shift+N")
        act_next.setShortcutContext(Qt.ApplicationShortcut)
        act_next.triggered.connect(lambda: self._adjust_day(1))
        nav_menu.addAction(act_next)
        self.addAction(act_next)

        act_today = QAction(strings._("today"), self)
        act_today.setShortcut("Ctrl+Shift+T")
        act_today.setShortcutContext(Qt.ApplicationShortcut)
        act_today.triggered.connect(self._adjust_today)
        nav_menu.addAction(act_today)
        self.addAction(act_today)

        act_close_tab = QAction(strings._("close_tab"), self)
        act_close_tab.setShortcut("Ctrl+W")
        act_close_tab.setShortcutContext(Qt.ApplicationShortcut)
        act_close_tab.triggered.connect(self._close_current_tab)
        nav_menu.addAction(act_close_tab)
        self.addAction(act_close_tab)

        act_find = QAction(strings._("find_on_page"), self)
        act_find.setShortcut(QKeySequence.Find)
        act_find.triggered.connect(self.findBar.show_bar)
        nav_menu.addAction(act_find)
        self.addAction(act_find)

        act_find_next = QAction(strings._("find_next"), self)
        act_find_next.setShortcut(QKeySequence.FindNext)
        act_find_next.triggered.connect(self.findBar.find_next)
        nav_menu.addAction(act_find_next)
        self.addAction(act_find_next)

        act_find_prev = QAction(strings._("find_previous"), self)
        act_find_prev.setShortcut(QKeySequence.FindPrevious)
        act_find_prev.triggered.connect(self.findBar.find_prev)
        nav_menu.addAction(act_find_prev)
        self.addAction(act_find_prev)

        # Help menu with drop-down
        help_menu = mb.addMenu("&" + strings._("help"))
        act_docs = QAction(strings._("documentation"), self)
        act_docs.setShortcut("Ctrl+Shift+D")
        act_docs.setShortcutContext(Qt.ApplicationShortcut)
        act_docs.triggered.connect(self._open_docs)
        help_menu.addAction(act_docs)
        self.addAction(act_docs)
        act_bugs = QAction(strings._("report_a_bug"), self)
        act_bugs.setShortcut("Ctrl+Shift+R")
        act_bugs.setShortcutContext(Qt.ApplicationShortcut)
        act_bugs.triggered.connect(self._open_bugs)
        help_menu.addAction(act_bugs)
        self.addAction(act_bugs)
        act_version = QAction(strings._("version"), self)
        act_version.setShortcut("Ctrl+Shift+V")
        act_version.setShortcutContext(Qt.ApplicationShortcut)
        act_version.triggered.connect(self._open_version)
        help_menu.addAction(act_version)
        self.addAction(act_version)

        # Autosave
        self._dirty = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_current)

        # Reminders / alarms
        self._reminder_timers: list[QTimer] = []

        # First load + mark dates in calendar with content
        if not self._load_unchecked_todos():
            self._load_selected_date()
        self._refresh_calendar_marks()

        # Hide tags and time log widgets if not enabled
        if not self.cfg.tags:
            self.tags.hide()
        if not self.cfg.time_log:
            self.time_log.hide()
            self.toolBar.actTimer.setVisible(False)
        if not self.cfg.reminders:
            self.upcoming_reminders.hide()
            self.toolBar.actAlarm.setVisible(False)
        if not self.cfg.documents:
            self.todays_documents.hide()
            self.toolBar.actDocuments.setVisible(False)

        # Restore window position from settings
        self._restore_window_position()

        # re-apply all runtime color tweaks when theme changes
        self.themes.themeChanged.connect(lambda _t: self._retheme_overrides())

        # apply once on startup so links / calendar colors are set immediately
        self._retheme_overrides()

        # Build any alarms for *today* from stored markdown
        self._rebuild_reminders_for_today()

        # Rollover unchecked todos automatically when the calendar day changes
        self._day_change_timer = QTimer(self)
        self._day_change_timer.setSingleShot(True)
        self._day_change_timer.timeout.connect(self._on_day_changed)
        self._schedule_next_day_change()

        # Ensure toolbar is definitely visible
        self.toolBar.setVisible(True)

    @property
    def editor(self) -> MarkdownEditor | None:
        """Get the currently active editor."""
        return self.tab_widget.currentWidget()

    def _call_editor(self, method_name, *args):
        """
        Call the relevant method of the MarkdownEditor class on bind
        """
        getattr(self.editor, method_name)(*args)

    # ----------- Database connection/key management methods ------------ #

    def _try_connect(self) -> bool:
        """
        Try to connect to the database.
        """
        try:
            self.db = DBManager(self.cfg)
            ok = self.db.connect()
            return ok
        except Exception as e:
            if str(e) == "file is not a database":
                error = strings._("db_key_incorrect")
            else:
                error = str(e)
            QMessageBox.critical(self, strings._("db_database_error"), error)
            return False

    def _prompt_for_key_until_valid(self, first_time: bool) -> bool:
        """
        Prompt for the SQLCipher key.
        """
        if first_time:
            title = strings._("set_an_encryption_key")
            message = strings._("set_an_encryption_key_explanation")
        else:
            title = strings._("unlock_encrypted_notebook")
            message = strings._("unlock_encrypted_notebook_explanation")
        while True:
            dlg = KeyPrompt(
                self, title, message, initial_db_path=self.cfg.path, show_db_change=True
            )
            if dlg.exec() != QDialog.Accepted:
                return False
            self.cfg.key = dlg.key()

            # Update DB path if the user changed it
            new_path = dlg.db_path()
            if new_path is not None and new_path != self.cfg.path:
                self.cfg.path = new_path
                # Persist immediately so next run is pre-filled with this file
                save_db_config(self.cfg)

            if self._try_connect():
                return True

    # ----------------- Tab and date management ----------------- #

    def _current_date_iso(self) -> str:
        d = self.calendar.selectedDate()
        return f"{d.year():04d}-{d.month():02d}-{d.day():02d}"

    def _date_key(self, qd: QDate) -> tuple[int, int, int]:
        return (qd.year(), qd.month(), qd.day())

    def _index_for_date_insert(self, date: QDate) -> int:
        """Return the index where a tab for `date` should be inserted (ascending order)."""
        key = self._date_key(date)
        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            d = getattr(w, "current_date", None)
            if isinstance(d, QDate) and d.isValid():
                if self._date_key(d) > key:
                    return i
        return self.tab_widget.count()

    def _reorder_tabs_by_date(self):
        """Reorder existing tabs by their date (ascending)."""
        bar = self.tab_widget.tabBar()
        dated, undated = [], []

        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            d = getattr(w, "current_date", None)
            if isinstance(d, QDate) and d.isValid():
                dated.append((d, w))
            else:
                undated.append(w)

        dated.sort(key=lambda t: self._date_key(t[0]))

        with QSignalBlocker(self.tab_widget):
            # Update labels to yyyy-MM-dd
            for d, w in dated:
                idx = self.tab_widget.indexOf(w)
                if idx != -1:
                    self.tab_widget.setTabText(idx, d.toString("yyyy-MM-dd"))

            # Move dated tabs into target positions 0..len(dated)-1
            for target_pos, (_, w) in enumerate(dated):
                cur = self.tab_widget.indexOf(w)
                if cur != -1 and cur != target_pos:
                    bar.moveTab(cur, target_pos)

            # Keep any undated pages (if they ever exist) after the dated ones
            start = len(dated)
            for offset, w in enumerate(undated):
                cur = self.tab_widget.indexOf(w)
                target = start + offset
                if cur != -1 and cur != target:
                    bar.moveTab(cur, target)

    def _tab_index_for_date(self, date: QDate) -> int:
        """Return the index of the tab showing `date`, or -1 if none."""
        iso = date.toString("yyyy-MM-dd")
        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            if (
                hasattr(w, "current_date")
                and w.current_date.toString("yyyy-MM-dd") == iso
            ):
                return i
        return -1

    def _open_date_in_tab(self, date: QDate):
        """Focus existing tab for `date`, or create it if needed. Returns the editor."""
        idx = self._tab_index_for_date(date)
        if idx != -1:
            self.tab_widget.setCurrentIndex(idx)
            # keep calendar selection in sync (don't trigger load)
            from PySide6.QtCore import QSignalBlocker

            with QSignalBlocker(self.calendar):
                self.calendar.setSelectedDate(date)
            QTimer.singleShot(0, self._focus_editor_now)
            return self.tab_widget.widget(idx)
        # not open yet -> create
        return self._create_new_tab(date)

    def _create_new_tab(self, date: QDate | None = None) -> MarkdownEditor:
        """Create a new editor tab and return the editor instance."""
        if date is None:
            date = self.calendar.selectedDate()

        # Deduplicate: if already open, just jump there
        existing = self._tab_index_for_date(date)
        if existing != -1:
            self.tab_widget.setCurrentIndex(existing)
            return self.tab_widget.widget(existing)

        editor = MarkdownEditor(self.themes)

        # Apply user's preferred font size
        self._apply_font_size(editor)

        # Set up the editor's event connections
        editor.currentCharFormatChanged.connect(lambda _f: self._sync_toolbar())
        editor.cursorPositionChanged.connect(self._sync_toolbar)
        editor.textChanged.connect(self._on_text_changed)

        # Set tab title
        tab_title = date.toString("yyyy-MM-dd")

        # Add the tab
        index = self.tab_widget.addTab(editor, tab_title)
        self.tab_widget.setCurrentIndex(index)

        # Load the date's content
        self._load_date_into_editor(date)

        # Store the date with the editor so we can save it later
        editor.current_date = date

        # Insert at sorted position
        tab_title = date.toString("yyyy-MM-dd")
        pos = self._index_for_date_insert(date)
        index = self.tab_widget.insertTab(pos, editor, tab_title)
        self.tab_widget.setCurrentIndex(index)

        return editor

    def _close_tab(self, index: int):
        """Close a tab at the given index."""
        if self.tab_widget.count() <= 1:
            # Don't close the last tab
            return

        editor = self.tab_widget.widget(index)
        if editor:
            # Save before closing
            self._save_editor_content(editor)
            self._dirty = False

        self.tab_widget.removeTab(index)

    def _close_current_tab(self):
        """Close the currently active tab via shortcuts (Ctrl+W)."""
        idx = self.tab_widget.currentIndex()
        if idx >= 0:
            self._close_tab(idx)

    def _on_tab_changed(self, index: int):
        """Handle tab change - reconnect toolbar and sync UI."""
        if index < 0:
            return

        # If we had pending edits, flush them from the tab we're leaving.
        try:
            self._save_timer.stop()  # avoid a pending autosave targeting the *new* tab
        except Exception:
            pass

        if getattr(self, "_prev_editor", None) is not None and self._dirty:
            self._save_editor_content(self._prev_editor)
            self._dirty = False  # we just saved the edited tab

        # Update calendar selection to match the tab
        editor = self.tab_widget.widget(index)
        if editor and hasattr(editor, "current_date"):
            with QSignalBlocker(self.calendar):
                self.calendar.setSelectedDate(editor.current_date)

            # update per-page tags for the active tab
            date_iso = editor.current_date.toString("yyyy-MM-dd")
            self._update_tag_views_for_date(date_iso)

        # Reconnect toolbar to new active editor
        self._sync_toolbar()

        # Focus the editor
        QTimer.singleShot(0, self._focus_editor_now)

        # Remember this as the "previous" editor for next switch
        self._prev_editor = editor

    def _date_from_calendar_pos(self, pos) -> QDate | None:
        """Translate a QCalendarWidget local pos to the QDate under the cursor."""
        view: QTableView = self.calendar.findChild(
            QTableView, "qt_calendar_calendarview"
        )
        if view is None:
            return None

        # Map calendar-local pos -> viewport pos
        vp_pos = view.viewport().mapFrom(self.calendar, pos)
        idx = view.indexAt(vp_pos)
        if not idx.isValid():
            return None

        model = view.model()

        # Account for optional headers
        start_col = (
            0
            if self.calendar.verticalHeaderFormat() == QCalendarWidget.NoVerticalHeader
            else 1
        )
        start_row = (
            0
            if self.calendar.horizontalHeaderFormat()
            == QCalendarWidget.NoHorizontalHeader
            else 1
        )

        # Find index of day 1 (first cell belonging to current month)
        first_index = None
        for r in range(start_row, model.rowCount()):
            for c in range(start_col, model.columnCount()):
                if model.index(r, c).data() == 1:
                    first_index = model.index(r, c)
                    break
            if first_index:
                break
        if first_index is None:
            return None

        # Find index of the last day of the current month
        last_day = (
            QDate(self.calendar.yearShown(), self.calendar.monthShown(), 1)
            .addMonths(1)
            .addDays(-1)
            .day()
        )
        last_index = None
        for r in range(model.rowCount() - 1, first_index.row() - 1, -1):
            for c in range(model.columnCount() - 1, start_col - 1, -1):
                if model.index(r, c).data() == last_day:
                    last_index = model.index(r, c)
                    break
            if last_index:
                break
        if last_index is None:
            return None

        # Determine if clicked cell belongs to prev/next month or current
        day = int(idx.data())
        year = self.calendar.yearShown()
        month = self.calendar.monthShown()

        before_first = (idx.row() < first_index.row()) or (
            idx.row() == first_index.row() and idx.column() < first_index.column()
        )
        after_last = (idx.row() > last_index.row()) or (
            idx.row() == last_index.row() and idx.column() > last_index.column()
        )

        if before_first:
            if month == 1:
                month = 12
                year -= 1
            else:
                month -= 1
        elif after_last:
            if month == 12:
                month = 1
                year += 1
            else:
                month += 1

        qd = QDate(year, month, day)
        return qd if qd.isValid() else None

    def _show_calendar_context_menu(self, pos):
        self._showing_context_menu = True  # so selectionChanged handler doesn't fire
        clicked_date = self._date_from_calendar_pos(pos)

        menu = QMenu(self)
        open_in_new_tab_action = menu.addAction(strings._("open_in_new_tab"))
        action = menu.exec_(self.calendar.mapToGlobal(pos))

        self._showing_context_menu = False

        if action == open_in_new_tab_action and clicked_date and clicked_date.isValid():
            self._open_date_in_tab(clicked_date)

    def _load_selected_date(self, date_iso=False, extra_data=False):
        """Load a date into the current editor"""
        if not date_iso:
            date_iso = self._current_date_iso()

        qd = QDate.fromString(date_iso, "yyyy-MM-dd")
        current_index = self.tab_widget.currentIndex()

        # Check if this date is already open in a *different* tab
        existing_idx = self._tab_index_for_date(qd)
        if existing_idx != -1 and existing_idx != current_index:
            # Date is already open in another tab - just switch to that tab
            self.tab_widget.setCurrentIndex(existing_idx)
            # Keep calendar in sync
            with QSignalBlocker(self.calendar):
                self.calendar.setSelectedDate(qd)
            QTimer.singleShot(0, self._focus_editor_now)
            return

        # Date not open in any other tab - load it into current tab
        # Keep calendar in sync
        with QSignalBlocker(self.calendar):
            self.calendar.setSelectedDate(qd)

        self._load_date_into_editor(qd, extra_data)
        self.editor.current_date = qd

        # Update tab title
        if current_index >= 0:
            self.tab_widget.setTabText(current_index, date_iso)

        # Keep tabs sorted by date
        self._reorder_tabs_by_date()

        # sync tags
        self._update_tag_views_for_date(date_iso)

    def _load_date_into_editor(self, date: QDate, extra_data=False):
        """Load a specific date's content into a given editor."""
        date_iso = date.toString("yyyy-MM-dd")
        text = self.db.get_entry(date_iso)
        if extra_data:
            # Append extra data as markdown
            if text and not text.endswith("\n"):
                text += "\n"
            text += extra_data
            # Force a save now so we don't lose it.
            self._set_editor_markdown_preserve_view(text)
            self._dirty = True
            self._save_date(date_iso, True)

        self._set_editor_markdown_preserve_view(text)
        self._dirty = False

    def _set_editor_markdown_preserve_view(self, markdown: str):

        # Save caret/selection and scroll
        cur = self.editor.textCursor()
        old_pos, old_anchor = cur.position(), cur.anchor()
        v = self.editor.verticalScrollBar().value()
        h = self.editor.horizontalScrollBar().value()

        # Only touch the doc if it actually changed
        self.editor.blockSignals(True)
        if self.editor.to_markdown() != markdown:
            self.editor.from_markdown(markdown)
        self.editor.blockSignals(False)

        # Restore scroll first
        self.editor.verticalScrollBar().setValue(v)
        self.editor.horizontalScrollBar().setValue(h)

        # Restore caret/selection (bounded to new doc length)
        doc_length = self.editor.document().characterCount() - 1
        old_pos = min(old_pos, doc_length)
        old_anchor = min(old_anchor, doc_length)

        cur = self.editor.textCursor()
        cur.setPosition(old_anchor)
        mode = (
            QTextCursor.KeepAnchor if old_anchor != old_pos else QTextCursor.MoveAnchor
        )
        cur.setPosition(old_pos, mode)
        self.editor.setTextCursor(cur)

        # Refresh highlights if the theme changed
        if hasattr(self, "findBar"):
            self.findBar.refresh()

    def _save_editor_content(self, editor: MarkdownEditor):
        """Save a specific editor's content to its associated date."""
        # Skip if DB is missing or not connected somehow.
        if not getattr(self, "db", None) or getattr(self.db, "conn", None) is None:
            return
        if not hasattr(editor, "current_date"):
            return
        date_iso = editor.current_date.toString("yyyy-MM-dd")
        md = editor.to_markdown()
        self.db.save_new_version(date_iso, md, note=strings._("autosave"))

    def _on_text_changed(self):
        self._dirty = True
        self._save_timer.start(5000)  # autosave after idle

    def _adjust_day(self, delta: int):
        """Move selection by delta days (negative for previous)."""
        d = self.calendar.selectedDate().addDays(delta)
        self.calendar.setSelectedDate(d)

    def _adjust_today(self):
        """Jump to today."""
        today = QDate.currentDate()
        self._create_new_tab(today)

    def _rollover_target_date(self, day: QDate) -> QDate:
        """
        Given a 'new day' (system date), return the date we should move
        unfinished todos *to*.

        By default, if the new day is Saturday or Sunday we skip ahead to the
        next Monday (i.e., "next available weekday"). If the optional setting
        `move_todos_include_weekends` is enabled, we move to the very next day
        even if it's a weekend.
        """
        if getattr(self.cfg, "move_todos_include_weekends", False):
            return day
        # Qt: Monday=1 ... Sunday=7
        dow = day.dayOfWeek()
        if dow >= 6:  # Saturday (6) or Sunday (7)
            return day.addDays(8 - dow)  # 6 -> +2, 7 -> +1 (next Monday)
        return day

    def _schedule_next_day_change(self) -> None:
        """
        Schedule a one-shot timer to fire shortly after the next midnight.
        """
        now = QDateTime.currentDateTime()
        tomorrow = now.date().addDays(1)
        # A couple of minutes after midnight to be safe
        next_run = QDateTime(tomorrow, QTime(0, 2))
        msecs = max(60_000, now.msecsTo(next_run))  # at least 1 minute
        self._day_change_timer.start(msecs)

    @Slot()
    def _on_day_changed(self) -> None:
        """
        Called when we've crossed into a new calendar day (according to the timer).
        Re-runs the rollover logic and refreshes the UI.
        """
        # Make the calendar show the *real* new day first
        today = QDate.currentDate()
        with QSignalBlocker(self.calendar):
            self.calendar.setSelectedDate(today)

        # Same logic as on startup
        if not self._load_unchecked_todos():
            self._load_selected_date()

        self._refresh_calendar_marks()
        self._rebuild_reminders_for_today()
        self._schedule_next_day_change()

    def _load_unchecked_todos(self, days_back: int = 7) -> bool:
        """
        Move unchecked checkbox items from the last `days_back` days
        into the rollover target date (today, or next Monday if today
        is a weekend).

        In addition to moving the unchecked checkbox *line* itself, this also
        moves any subsequent lines that belong to that unchecked item, stopping
        at the next *checked* checkbox line **or** the next markdown heading.

        This allows code fences, collapsed blocks, and notes under a todo to
        travel with it without accidentally pulling in the next section.

        Returns True if any items were moved, False otherwise.
        """
        if not getattr(self.cfg, "move_todos", False):
            return False

        if not getattr(self, "db", None):
            return False

        today = QDate.currentDate()
        target_date = self._rollover_target_date(today)
        target_iso = target_date.toString("yyyy-MM-dd")

        # Regexes for markdown headings and checkboxes
        heading_re = re.compile(r"^\s{0,3}(#+)\s+(.*)$")
        unchecked_re = re.compile(r"^(\s*)-\s*\[[\s☐]\]\s+(.*)$")
        checked_re = re.compile(r"^(\s*)-\s*\[[xX☑]\]\s+(.*)$")
        fence_re = re.compile(r"^\s*(`{3,}|~{3,})")

        def _normalize_heading(text: str) -> str:
            """
            Strip trailing closing hashes and whitespace, e.g.
            "## Foo ###" -> "Foo"
            """
            text = text.strip()
            text = re.sub(r"\s+#+\s*$", "", text)
            return text.strip()

        def _update_fence_state(
            line: str, in_fence: bool, fence_marker: str | None
        ) -> tuple[bool, str | None]:
            """
            Track fenced code blocks (``` / ~~~). We ignore checkbox markers inside
            fences so we don't accidentally split/move based on "- [x]" that appears
            in code.
            """
            m = fence_re.match(line)
            if not m:
                return in_fence, fence_marker

            marker = m.group(1)
            if not in_fence:
                return True, marker

            # Close only when we see a fence of the same char and >= length
            if (
                fence_marker
                and marker[0] == fence_marker[0]
                and len(marker) >= len(fence_marker)
            ):
                return False, None

            return in_fence, fence_marker

        def _is_list_item(line: str) -> bool:
            s = line.lstrip()
            return bool(
                re.match(r"^([-*+]\s+|\d+\.\s+)", s)
                or unchecked_re.match(line)
                or checked_re.match(line)
            )

        def _insert_blocks_under_heading(
            target_lines: list[str],
            heading_level: int,
            heading_text: str,
            blocks: list[list[str]],
        ) -> list[str]:
            """Ensure a heading exists and append blocks to the end of its section."""
            normalized = _normalize_heading(heading_text)

            # 1) Find existing heading with same text (any level)
            start_idx = None
            effective_level = None
            for idx, line in enumerate(target_lines):
                m = heading_re.match(line)
                if not m:
                    continue
                level = len(m.group(1))
                text = _normalize_heading(m.group(2))
                if text == normalized:
                    start_idx = idx
                    effective_level = level
                    break

            # 2) If not found, create a new heading at the end
            if start_idx is None:
                if target_lines and target_lines[-1].strip():
                    target_lines.append("")  # blank line before new heading
                target_lines.append(f"{'#' * heading_level} {heading_text}")
                start_idx = len(target_lines) - 1
                effective_level = heading_level

            # 3) Find the end of this heading's section
            end_idx = len(target_lines)
            for i in range(start_idx + 1, len(target_lines)):
                m = heading_re.match(target_lines[i])
                if m and len(m.group(1)) <= effective_level:
                    end_idx = i
                    break

            # 4) Insert before any trailing blank lines in the section
            insert_at = end_idx
            while (
                insert_at > start_idx + 1 and target_lines[insert_at - 1].strip() == ""
            ):
                insert_at -= 1

            # Insert blocks (preserve internal blank lines)
            for block in blocks:
                if not block:
                    continue

                # Avoid gluing a paragraph to the new block unless both look like list items
                if (
                    insert_at > start_idx + 1
                    and target_lines[insert_at - 1].strip() != ""
                    and block[0].strip() != ""
                    and not (
                        _is_list_item(target_lines[insert_at - 1])
                        and _is_list_item(block[0])
                    )
                ):
                    target_lines.insert(insert_at, "")
                    insert_at += 1

                for line in block:
                    target_lines.insert(insert_at, line)
                    insert_at += 1

            return target_lines

        def _prune_empty_headings(src_lines: list[str]) -> list[str]:
            """Remove markdown headings whose section became empty.

            The rollover logic removes unchecked todo *blocks* but intentionally keeps
            headings on the source day so we can re-create the same section on the
            target day. If a heading ends up with no remaining content (including
            empty subheadings), we should remove it from the source day too.

            Headings inside fenced code blocks are ignored.
            """

            # Identify headings (outside fences) and their levels
            heading_levels: dict[int, int] = {}
            heading_indices: list[int] = []

            in_f = False
            f_mark: str | None = None
            for idx, ln in enumerate(src_lines):
                if not in_f:
                    m = heading_re.match(ln)
                    if m:
                        heading_indices.append(idx)
                        heading_levels[idx] = len(m.group(1))
                in_f, f_mark = _update_fence_state(ln, in_f, f_mark)

            if not heading_indices:
                return src_lines

            # Compute each heading's section boundary: next heading with level <= current
            boundary: dict[int, int] = {}
            stack: list[int] = []
            for idx in heading_indices:
                lvl = heading_levels[idx]
                while stack and lvl <= heading_levels[stack[-1]]:
                    boundary[stack.pop()] = idx
                stack.append(idx)
            for idx in stack:
                boundary[idx] = len(src_lines)

            # Build parent/children relationships based on heading levels
            children: dict[int, list[int]] = {}
            parent_stack: list[int] = []
            for idx in heading_indices:
                lvl = heading_levels[idx]
                while parent_stack and lvl <= heading_levels[parent_stack[-1]]:
                    parent_stack.pop()
                if parent_stack:
                    children.setdefault(parent_stack[-1], []).append(idx)
                parent_stack.append(idx)

            # Determine whether each heading has any non-heading, non-blank content in its span
            has_body: dict[int, bool] = {}
            for h_idx in heading_indices:
                end = boundary[h_idx]
                body = False
                in_f = False
                f_mark = None
                for j in range(h_idx + 1, end):
                    ln = src_lines[j]
                    if not in_f:
                        if ln.strip() and not heading_re.match(ln):
                            body = True
                            break
                    in_f, f_mark = _update_fence_state(ln, in_f, f_mark)
                has_body[h_idx] = body

            # Bottom-up: keep headings that have body content or any kept child headings
            keep: dict[int, bool] = {}
            for h_idx in reversed(heading_indices):
                keep_child = any(keep.get(ch, False) for ch in children.get(h_idx, []))
                keep[h_idx] = has_body[h_idx] or keep_child

            remove_set = {idx for idx, k in keep.items() if not k}
            if not remove_set:
                return src_lines

            # Remove empty headings and any immediate blank lines following them
            out: list[str] = []
            i = 0
            while i < len(src_lines):
                if i in remove_set:
                    i += 1
                    while i < len(src_lines) and src_lines[i].strip() == "":
                        i += 1
                    continue
                out.append(src_lines[i])
                i += 1

            # Normalize excessive blank lines created by removals
            cleaned: list[str] = []
            prev_blank = False
            for ln in out:
                blank = ln.strip() == ""
                if blank and prev_blank:
                    continue
                cleaned.append(ln)
                prev_blank = blank

            while cleaned and cleaned[0].strip() == "":
                cleaned.pop(0)
            while cleaned and cleaned[-1].strip() == "":
                cleaned.pop()
            return cleaned

        # Collect moved blocks as (heading_info, block_lines)
        # heading_info is either None or (level, heading_text)
        moved_blocks: list[tuple[tuple[int, str] | None, list[str]]] = []
        any_moved = False

        # Look back N days (yesterday = 1, up to `days_back`)
        for delta in range(1, days_back + 1):
            src_date = today.addDays(-delta)
            src_iso = src_date.toString("yyyy-MM-dd")
            text = self.db.get_entry(src_iso)
            if not text:
                continue

            lines = text.split("\n")
            remaining_lines: list[str] = []
            moved_from_this_day = False
            current_heading: tuple[int, str] | None = None

            in_fence = False
            fence_marker: str | None = None

            i = 0
            while i < len(lines):
                line = lines[i]

                # If we're not in a fenced code block, we can interpret headings/checkboxes
                if not in_fence:
                    # Track the last seen heading (# / ## / ###)
                    m_head = heading_re.match(line)
                    if m_head:
                        level = len(m_head.group(1))
                        heading_text = _normalize_heading(m_head.group(2))
                        if level <= 3:
                            current_heading = (level, heading_text)
                        # Keep headings in the original day (only headings ABOVE a moved block are "carried")
                        remaining_lines.append(line)
                        in_fence, fence_marker = _update_fence_state(
                            line, in_fence, fence_marker
                        )
                        i += 1
                        continue

                    # Start of an unchecked checkbox block
                    m_unchecked = unchecked_re.match(line)
                    if m_unchecked:
                        indent = m_unchecked.group(1) or ""
                        item_text = m_unchecked.group(2)
                        block: list[str] = [f"{indent}- [ ] {item_text}"]

                        i += 1
                        # Consume subsequent lines until the next *checked* checkbox
                        # (ignoring any "- [x]" that appear inside fenced code blocks)
                        block_in_fence = in_fence
                        block_fence_marker = fence_marker

                        while i < len(lines):
                            nxt = lines[i]

                            # If we're not inside a fence, a checked checkbox ends the block,
                            # otherwise a new heading does as well.
                            if not block_in_fence and (
                                checked_re.match(nxt) or heading_re.match(nxt)
                            ):
                                break

                            # Normalize any unchecked checkbox lines inside the block
                            m_inner_unchecked = (
                                unchecked_re.match(nxt) if not block_in_fence else None
                            )
                            if m_inner_unchecked:
                                inner_indent = m_inner_unchecked.group(1) or ""
                                inner_text = m_inner_unchecked.group(2)
                                block.append(f"{inner_indent}- [ ] {inner_text}")
                            else:
                                block.append(nxt)

                            # Update fence state after consuming the line
                            block_in_fence, block_fence_marker = _update_fence_state(
                                nxt, block_in_fence, block_fence_marker
                            )
                            i += 1

                        # Carry the last heading *above* the unchecked checkbox
                        moved_blocks.append((current_heading, block))
                        moved_from_this_day = True
                        any_moved = True

                        # We consumed the block; keep scanning from the checked checkbox (or EOF)
                        continue

                # Default: keep the line on the original day
                remaining_lines.append(line)
                in_fence, fence_marker = _update_fence_state(
                    line, in_fence, fence_marker
                )
                i += 1

            if moved_from_this_day:
                remaining_lines = _prune_empty_headings(remaining_lines)
                modified_text = "\n".join(remaining_lines)
                # Save the cleaned-up source day
                self.db.save_new_version(
                    src_iso,
                    modified_text,
                    strings._("unchecked_checkbox_items_moved_to_next_day"),
                )

        if not any_moved:
            return False

        # --- Merge all moved blocks into the *target* date ---

        target_text = self.db.get_entry(target_iso) or ""
        # Treat a whitespace-only target note as truly empty; otherwise we can
        # end up appending the new heading *after* leading blank lines (e.g. if
        # a newly-created empty day was previously saved as just "\n").
        if not target_text.strip():
            target_lines = []
        else:
            target_lines = target_text.split("\n")

        by_heading: dict[tuple[int, str], list[list[str]]] = {}
        plain_blocks: list[list[str]] = []

        for heading_info, block in moved_blocks:
            if heading_info is None:
                plain_blocks.append(block)
            else:
                by_heading.setdefault(heading_info, []).append(block)

        # First insert all blocks that have headings
        for (level, heading_text), blocks in by_heading.items():
            target_lines = _insert_blocks_under_heading(
                target_lines, level, heading_text, blocks
            )

        # Then append all blocks without headings at the end, like before
        if plain_blocks:
            if target_lines and target_lines[-1].strip():
                target_lines.append("")  # one blank line before the "unsectioned" todos
            first = True
            for block in plain_blocks:
                if not block:
                    continue
                if (
                    not first
                    and target_lines
                    and target_lines[-1].strip() != ""
                    and block[0].strip() != ""
                    and not (
                        _is_list_item(target_lines[-1]) and _is_list_item(block[0])
                    )
                ):
                    target_lines.append("")
                target_lines.extend(block)
                first = False

        new_target_text = "\n".join(target_lines)
        if not new_target_text.endswith("\n"):
            new_target_text += "\n"

        # Save the updated target date and load it into the editor
        self.db.save_new_version(
            target_iso,
            new_target_text,
            strings._("unchecked_checkbox_items_moved_to_next_day"),
        )
        self._load_selected_date(target_iso)
        return True

    def _on_date_changed(self):
        """
        When the calendar selection changes, save the previous day's note if dirty,
        so we don't lose that text, then load the newly selected day into current tab.
        """
        # Skip if we're showing a context menu (right-click shouldn't load dates)
        if getattr(self, "_showing_context_menu", False):
            return

        # Stop pending autosave and persist current buffer if needed
        try:
            self._save_timer.stop()
        except Exception:
            pass

        # Save the current editor's content if dirty
        if hasattr(self.editor, "current_date") and self._dirty:
            prev_date_iso = self.editor.current_date.toString("yyyy-MM-dd")
            self._save_date(prev_date_iso, explicit=False)

        # Now load the newly selected date
        new_date = self.calendar.selectedDate()
        current_index = self.tab_widget.currentIndex()

        # Check if this date is already open in a *different* tab
        existing_idx = self._tab_index_for_date(new_date)
        if existing_idx != -1 and existing_idx != current_index:
            # Date is already open in another tab - just switch to that tab
            self.tab_widget.setCurrentIndex(existing_idx)
            QTimer.singleShot(0, self._focus_editor_now)
            return

        # Date not open in any other tab - load it into current tab
        self._load_date_into_editor(new_date)
        self.editor.current_date = new_date

        # Update tab title
        if current_index >= 0:
            self.tab_widget.setTabText(current_index, new_date.toString("yyyy-MM-dd"))

        # Update tags for the newly loaded page
        date_iso = new_date.toString("yyyy-MM-dd")
        self._update_tag_views_for_date(date_iso)

        # Keep tabs sorted by date
        self._reorder_tabs_by_date()

    def _save_date(self, date_iso: str, explicit: bool = False, note: str = "autosave"):
        """
        Save editor contents into the given date. Shows status on success.
        explicit=True means user invoked Save: show feedback even if nothing changed.
        """
        # Bail out if there is no DB connection (can happen during construction/teardown)
        if not getattr(self.db, "conn", None):
            return

        if not self._dirty and not explicit:
            return
        text = self.editor.to_markdown() if hasattr(self, "editor") else ""
        self.db.save_new_version(date_iso, text, note)
        self._dirty = False
        self._refresh_calendar_marks()
        # Feedback in the status bar
        from datetime import datetime as _dt

        self.statusBar().showMessage(
            strings._("saved") + f" {date_iso}: {_dt.now().strftime('%H:%M:%S')}", 2000
        )

    def _save_current(self, explicit: bool = False):
        """Save the current editor's content."""
        try:
            self._save_timer.stop()
        except Exception:
            pass

        if explicit:
            # Prompt for a note
            dlg = SaveDialog(self)
            if dlg.exec() != QDialog.Accepted:
                return
            note = dlg.note_text()
        else:
            note = strings._("autosave")
        # Save the current editor's date
        date_iso = self.editor.current_date.toString("yyyy-MM-dd")
        self._save_date(date_iso, explicit, note)
        try:
            self._save_timer.start()
        except Exception:
            pass

    # ----------------- Some theme helpers -------------------#
    def _apply_font_size(self, editor: MarkdownEditor) -> None:
        """Apply the saved font size to a newly created editor."""
        size = self.cfg.font_size
        editor.qfont.setPointSize(size)
        editor.setFont(editor.qfont)
        self.cfg.font_size = size
        # save size to settings
        cfg = load_db_config()
        cfg.font_size = self.cfg.font_size
        save_db_config(cfg)

    def _retheme_overrides(self):
        self._apply_search_highlights(getattr(self, "_search_highlighted_dates", set()))
        self.calendar.update()
        self.editor.viewport().update()

    # --------------- Search sidebar/results helpers ---------------- #

    def _on_search_dates_changed(self, date_strs: list[str]):
        dates = set()
        for ds in date_strs or []:
            qd = QDate.fromString(ds, "yyyy-MM-dd")
            if qd.isValid():
                dates.add(qd)
        self._apply_search_highlights(dates)

    def _apply_search_highlights(self, dates: set):
        pal = self.palette()
        base = pal.base().color()
        hi = pal.highlight().color()
        # Blend highlight with base so it looks soft in both modes
        blend = QColor(
            (2 * hi.red() + base.red()) // 3,
            (2 * hi.green() + base.green()) // 3,
            (2 * hi.blue() + base.blue()) // 3,
        )
        yellow = QBrush(blend)
        old = getattr(self, "_search_highlighted_dates", set())

        for d in old - dates:  # clear removed
            fmt = self.calendar.dateTextFormat(d)
            fmt.setBackground(Qt.transparent)
            self.calendar.setDateTextFormat(d, fmt)

        for d in dates:  # apply new/current
            fmt = self.calendar.dateTextFormat(d)
            fmt.setBackground(yellow)
            self.calendar.setDateTextFormat(d, fmt)

        self._search_highlighted_dates = dates

    def _refresh_calendar_marks(self):
        """Make days with entries bold, but keep any search highlight backgrounds."""
        for d in getattr(self, "_marked_dates", set()):
            fmt = self.calendar.dateTextFormat(d)
            fmt.setFontWeight(QFont.Weight.Normal)  # remove bold only
            self.calendar.setDateTextFormat(d, fmt)
        self._marked_dates = set()
        if self.db.conn is not None:
            for date_iso in self.db.dates_with_content():
                qd = QDate.fromString(date_iso, "yyyy-MM-dd")
                if qd.isValid():
                    fmt = self.calendar.dateTextFormat(qd)
                    fmt.setFontWeight(QFont.Weight.Bold)  # add bold only
                    self.calendar.setDateTextFormat(qd, fmt)
                    self._marked_dates.add(qd)

    # -------------------- UI handlers ------------------- #

    def _bind_toolbar(self):
        if getattr(self, "_toolbar_bound", False):
            return
        tb = self.toolBar

        # keep refs so we never create new lambdas (prevents accidental dupes)
        self._tb_bold = lambda: self._call_editor("apply_weight")
        self._tb_italic = lambda: self._call_editor("apply_italic")
        self._tb_strike = lambda: self._call_editor("apply_strikethrough")
        self._tb_code = lambda: self._call_editor("apply_code")
        self._tb_heading = lambda level: self._call_editor("apply_heading", level)
        self._tb_bullets = lambda: self._call_editor("toggle_bullets")
        self._tb_numbers = lambda: self._call_editor("toggle_numbers")
        self._tb_checkboxes = lambda: self._call_editor("toggle_checkboxes")
        self._tb_alarm = self._on_alarm_requested
        self._tb_timer = self._on_timer_requested
        self._tb_documents = self._on_documents_requested
        self._tb_font_larger = self._on_font_larger_requested
        self._tb_font_smaller = self._on_font_smaller_requested

        tb.boldRequested.connect(self._tb_bold)
        tb.italicRequested.connect(self._tb_italic)
        tb.strikeRequested.connect(self._tb_strike)
        tb.codeRequested.connect(self._tb_code)
        tb.headingRequested.connect(self._tb_heading)
        tb.bulletsRequested.connect(self._tb_bullets)
        tb.numbersRequested.connect(self._tb_numbers)
        tb.checkboxesRequested.connect(self._tb_checkboxes)
        tb.alarmRequested.connect(self._tb_alarm)
        tb.timerRequested.connect(self._tb_timer)
        tb.documentsRequested.connect(self._tb_documents)
        tb.insertImageRequested.connect(self._on_insert_image)
        tb.historyRequested.connect(self._open_history)
        tb.fontSizeLargerRequested.connect(self._tb_font_larger)
        tb.fontSizeSmallerRequested.connect(self._tb_font_smaller)

        self._toolbar_bound = True

    def _sync_toolbar(self):
        """
        Keep the toolbar "sticky" by reflecting the markdown state at the current caret/selection.
        """
        c = self.editor.textCursor()
        line = c.block().text()

        # Inline styles (markdown-aware)
        bold_on = bool(getattr(self.editor, "is_markdown_bold_active", lambda: False)())
        italic_on = bool(
            getattr(self.editor, "is_markdown_italic_active", lambda: False)()
        )
        strike_on = bool(
            getattr(self.editor, "is_markdown_strike_active", lambda: False)()
        )

        # Block signals so setChecked() doesn't re-trigger actions
        QSignalBlocker(self.toolBar.actBold)
        QSignalBlocker(self.toolBar.actItalic)
        QSignalBlocker(self.toolBar.actStrike)

        self.toolBar.actBold.setChecked(bold_on)
        self.toolBar.actItalic.setChecked(italic_on)
        self.toolBar.actStrike.setChecked(strike_on)

        # Headings: infer from leading markdown markers
        heading_level = 0
        m = re.match(r"^\s*(#{1,3})\s+", line)
        if m:
            heading_level = len(m.group(1))

        QSignalBlocker(self.toolBar.actH1)
        QSignalBlocker(self.toolBar.actH2)
        QSignalBlocker(self.toolBar.actH3)
        QSignalBlocker(self.toolBar.actNormal)

        self.toolBar.actH1.setChecked(heading_level == 1)
        self.toolBar.actH2.setChecked(heading_level == 2)
        self.toolBar.actH3.setChecked(heading_level == 3)
        self.toolBar.actNormal.setChecked(heading_level == 0)

        # Lists: infer from leading markers on the current line
        bullets_on = bool(re.match(r"^\s*(?:•|-|\*)\s+", line))
        numbers_on = bool(re.match(r"^\s*\d+\.\s+", line))
        checkboxes_on = bool(re.match(r"^\s*[☐☑]\s+", line))

        QSignalBlocker(self.toolBar.actBullets)
        QSignalBlocker(self.toolBar.actNumbers)
        QSignalBlocker(self.toolBar.actCheckboxes)

        self.toolBar.actBullets.setChecked(bullets_on)
        self.toolBar.actNumbers.setChecked(numbers_on)
        self.toolBar.actCheckboxes.setChecked(checkboxes_on)

    def _change_font_size(self, delta: int) -> None:
        """Change font size for all editor tabs and save the setting."""
        old_size = self.cfg.font_size
        new_size = old_size + delta

        self.cfg.font_size = new_size
        # save size to settings
        cfg = load_db_config()
        cfg.font_size = self.cfg.font_size
        save_db_config(cfg)

        # Apply font size change to all open editors
        self._apply_font_size_to_all_tabs(new_size)

    def _apply_font_size_to_all_tabs(self, size: int) -> None:
        for i in range(self.tab_widget.count()):
            ed = self.tab_widget.widget(i)
            if not isinstance(ed, MarkdownEditor):
                continue
            ed.qfont.setPointSize(size)
            ed.setFont(ed.qfont)

    def _on_font_larger_requested(self) -> None:
        self._change_font_size(+1)

    def _on_font_smaller_requested(self) -> None:
        self._change_font_size(-1)

    # ----------- Alarms handler ------------#
    def _on_alarm_requested(self):
        self.upcoming_reminders._add_reminder()

    def _on_timer_requested(self):
        """Toggle the embedded Pomodoro timer for the current line."""
        action = self.toolBar.actTimer

        # Turned on -> start a new timer for the current line
        if action.isChecked():
            editor = getattr(self, "editor", None)
            if editor is None:
                # No editor; immediately reset the toggle
                action.setChecked(False)
                return

            # Get the current line text
            line_text = editor.get_current_line_task_text()
            if not line_text:
                line_text = strings._("pomodoro_time_log_default_text")

            # Get current date
            date_iso = self.editor.current_date.toString("yyyy-MM-dd")

            # Start the timer embedded in the sidebar
            self.pomodoro_manager.start_timer_for_line(line_text, date_iso)
        else:
            # Turned off -> cancel any running timer and remove the widget
            self.pomodoro_manager.cancel_timer()

    def _send_reminder_webhook(self, text: str):
        if self.cfg.reminders and self.cfg.reminders_webhook_url:
            reminder_webhook = ReminderWebHook(text)
            reminder_webhook._send()

    def _show_flashing_reminder(self, text: str):
        """
        Show a small flashing dialog and request attention from the OS.
        Called by reminder timers.
        """
        # Ask OS to flash / bounce our app in the dock/taskbar
        QApplication.alert(self, 0)

        # Try to bring the window to the front
        self.showNormal()
        self.raise_()
        self.activateWindow()

        # Simple dialog with a flashing background to reinforce the alert
        dlg = QDialog(self)
        dlg.setWindowTitle(strings._("reminder"))
        dlg.setModal(True)
        dlg.setMinimumWidth(400)

        layout = QVBoxLayout(dlg)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)

        btn = QPushButton(strings._("dismiss"))
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)

        flash_timer = QTimer(dlg)
        flash_state = {"on": False}

        def toggle():
            flash_state["on"] = not flash_state["on"]
            if flash_state["on"]:
                dlg.setStyleSheet("background-color: #3B3B3B;")
            else:
                dlg.setStyleSheet("")

        flash_timer.timeout.connect(toggle)
        flash_timer.start(500)  # ms

        dlg.exec()

        flash_timer.stop()

    def _clear_reminder_timers(self):
        """Stop and delete any existing reminder timers."""
        for t in self._reminder_timers:
            try:
                t.stop()
                t.deleteLater()
            except Exception:
                pass
        self._reminder_timers = []

    def _rebuild_reminders_for_today(self):
        """
        Scan the markdown for today's date and create QTimers
        only for alarms on the *current day* (system date).
        """
        # We only ever set timers for the real current date
        today = QDate.currentDate()
        today_iso = today.toString("yyyy-MM-dd")

        # Clear any previously scheduled "today" reminders
        self._clear_reminder_timers()

        # Prefer live editor content if it is showing today's page
        text = ""
        if (
            hasattr(self, "editor")
            and hasattr(self.editor, "current_date")
            and self.editor.current_date == today
        ):
            text = self.editor.to_markdown()
        else:
            # Fallback to DB: still only today's date
            text = self.db.get_entry(today_iso) if hasattr(self, "db") else ""

        if not text:
            return

        now = QDateTime.currentDateTime()

        for line in text.splitlines():
            # Look for "⏰ HH:MM" anywhere in the line
            m = re.search(r"⏰\s*(\d{1,2}):(\d{2})", line)
            if not m:
                continue

            hour = int(m.group(1))
            minute = int(m.group(2))

            t = QTime(hour, minute)
            if not t.isValid():
                continue

            target = QDateTime(today, t)

            # Skip alarms that are already in the past
            if target <= now:
                continue

            # The reminder text is the part before the symbol
            reminder_text = line.split("⏰", 1)[0].strip()
            if not reminder_text:
                reminder_text = strings._("reminder_no_text_fallback")

            msecs = now.msecsTo(target)
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(
                lambda txt=reminder_text: self._show_flashing_reminder(txt)
            )
            timer.start(msecs)
            self._reminder_timers.append(timer)

    # ----------- Documents handler ------------#
    def _on_documents_requested(self):
        documents_dlg = DocumentsDialog(self.db, self)
        documents_dlg.exec()
        # Refresh recent documents after any changes
        if hasattr(self, "todays_documents"):
            self.todays_documents.reload()

    # ----------- History handler ------------#
    def _open_history(self):
        if hasattr(self.editor, "current_date"):
            date_iso = self.editor.current_date.toString("yyyy-MM-dd")
        else:
            date_iso = self._current_date_iso()

        dlg = HistoryDialog(self.db, date_iso, self, themes=self.themes)
        if dlg.exec() == QDialog.Accepted:
            # refresh editor + calendar (head pointer may have changed)
            self._load_selected_date(date_iso)
            self._refresh_calendar_marks()

    # ----------- Image insert handler ------------#
    def _on_insert_image(self):
        # Let the user pick one or many images
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            strings._("insert_images"),
            "",
            strings._("images") + "(*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
        )
        if not paths:
            return
        # Insert each image
        for path_str in paths:
            self.editor.insert_image_from_path(Path(path_str))

    # ----------- Tags handler ----------------#
    def _update_tag_views_for_date(self, date_iso: str):
        if hasattr(self, "tags"):
            self.tags.set_current_date(date_iso)
        if hasattr(self, "time_log"):
            self.time_log.set_current_date(date_iso)
        if hasattr(self, "todays_documents"):
            self.todays_documents.set_current_date(date_iso)

    def _on_tag_added(self):
        """Called when a tag is added - trigger autosave for current page"""
        # Use QTimer to defer the save slightly, avoiding re-entrancy issues
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self._do_tag_save)

    def _do_tag_save(self):
        """Actually perform the save after tag is added"""
        if hasattr(self, "editor") and hasattr(self.editor, "current_date"):
            date_iso = self.editor.current_date.toString("yyyy-MM-dd")

            # Get current editor content
            text = self.editor.to_markdown()

            # Save the content (or blank if page is empty)
            # This ensures the page shows up in tag browser
            self.db.save_new_version(date_iso, text, note="Tag added")
            self._dirty = False
            self._refresh_calendar_marks()
            from datetime import datetime as _dt

            self.statusBar().showMessage(
                strings._("saved") + f" {date_iso}: {_dt.now().strftime('%H:%M:%S')}",
                2000,
            )

    def _on_tag_activated(self, tag_name_or_date: str):
        # If it's a date (YYYY-MM-DD format), load it
        if len(tag_name_or_date) == 10 and tag_name_or_date.count("-") == 2:
            self._load_selected_date(tag_name_or_date)
        else:
            # It's a tag name, open the tag browser
            from .tag_browser import TagBrowserDialog

            dlg = TagBrowserDialog(self.db, self, focus_tag=tag_name_or_date)
            dlg.openDateRequested.connect(self._load_selected_date)
            dlg.tagsModified.connect(self._refresh_current_page_tags)
            dlg.exec()

    def _refresh_current_page_tags(self):
        """Refresh the tag chips for the current page (after tag browser changes)"""
        if hasattr(self, "tags") and hasattr(self.editor, "current_date"):
            date_iso = self.editor.current_date.toString("yyyy-MM-dd")
            self.tags.set_current_date(date_iso)
            if self.tags.toggle_btn.isChecked():
                self.tags._reload_tags()

    # ----------- Settings handler ------------#
    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self.db, self)
        if dlg.exec() != QDialog.Accepted:
            return

        new_cfg = dlg.config
        old_path = self.cfg.path

        # Update in-memory config from the dialog
        self.cfg.path = new_cfg.path
        self.cfg.key = new_cfg.key
        self.cfg.idle_minutes = getattr(new_cfg, "idle_minutes", self.cfg.idle_minutes)
        self.cfg.theme = getattr(new_cfg, "theme", self.cfg.theme)
        self.cfg.move_todos = getattr(new_cfg, "move_todos", self.cfg.move_todos)
        self.cfg.move_todos_include_weekends = getattr(
            new_cfg,
            "move_todos_include_weekends",
            getattr(self.cfg, "move_todos_include_weekends", False),
        )
        self.cfg.tags = getattr(new_cfg, "tags", self.cfg.tags)
        self.cfg.time_log = getattr(new_cfg, "time_log", self.cfg.time_log)
        self.cfg.reminders = getattr(new_cfg, "reminders", self.cfg.reminders)
        self.cfg.reminders_webhook_url = getattr(
            new_cfg, "reminders_webhook_url", self.cfg.reminders_webhook_url
        )
        self.cfg.reminders_webhook_secret = getattr(
            new_cfg, "reminders_webhook_secret", self.cfg.reminders_webhook_secret
        )
        self.cfg.documents = getattr(new_cfg, "documents", self.cfg.documents)
        self.cfg.invoicing = getattr(new_cfg, "invoicing", self.cfg.invoicing)
        self.cfg.locale = getattr(new_cfg, "locale", self.cfg.locale)
        self.cfg.font_size = getattr(new_cfg, "font_size", self.cfg.font_size)

        # Persist once
        save_db_config(self.cfg)
        # Apply idle setting immediately (restart the timer with new interval if it changed)
        self._apply_idle_minutes(self.cfg.idle_minutes)
        # Apply font size to all tabs
        self._apply_font_size_to_all_tabs(self.cfg.font_size)

        # If the DB path changed, reconnect
        if self.cfg.path != old_path:
            self.db.close()
            if not self._prompt_for_key_until_valid(first_time=False):
                QMessageBox.warning(
                    self,
                    strings._("reopen_failed"),
                    strings._("could_not_unlock_database_at_new_path"),
                )
                return
            self._load_selected_date()
            self._refresh_calendar_marks()

        # Show or hide the tags and time_log features depending on what the settings are now.
        self.tags.hide() if not self.cfg.tags else self.tags.show()
        if not self.cfg.time_log:
            self.time_log.hide()
            self.toolBar.actTimer.setVisible(False)
        else:
            self.time_log.show()
            self.toolBar.actTimer.setVisible(True)
        if not self.cfg.reminders:
            self.upcoming_reminders.hide()
            self.toolBar.actAlarm.setVisible(False)
        else:
            self.upcoming_reminders.show()
            self.toolBar.actAlarm.setVisible(True)
        if not self.cfg.documents:
            self.todays_documents.hide()
            self.toolBar.actDocuments.setVisible(False)
        else:
            self.todays_documents.show()
            self.toolBar.actDocuments.setVisible(True)

    # ------------ Statistics handler --------------- #

    def _open_statistics(self):
        if not getattr(self, "db", None) or self.db.conn is None:
            return

        dlg = StatisticsDialog(self.db, self)

        if hasattr(dlg, "_heatmap"):

            def on_date_clicked(d: datetime.date):
                qd = QDate(d.year, d.month, d.day)
                self._open_date_in_tab(qd)

            dlg._heatmap.date_clicked.connect(on_date_clicked)
        dlg.exec()

    # ------------ Window positioning --------------- #
    def _restore_window_position(self):
        geom = self.settings.value("main/geometry", None)
        state = self.settings.value("main/windowState", None)
        was_max = self.settings.value("main/maximized", False, type=bool)

        if geom is not None:
            self.restoreGeometry(geom)
            if state is not None:
                self.restoreState(state)
            if not self._rect_on_any_screen(self.frameGeometry()):
                self._move_to_cursor_screen_center()
        else:
            # First run: place window on the screen where the mouse cursor is.
            self._move_to_cursor_screen_center()

        # If it was maximized, do that AFTER the window exists in the event loop.
        if was_max:
            QTimer.singleShot(0, self.showMaximized)

    def _rect_on_any_screen(self, rect):
        for sc in QGuiApplication.screens():
            if sc.availableGeometry().intersects(rect):
                return True
        return False

    def _move_to_cursor_screen_center(self):
        screen = (
            QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        )
        r = screen.availableGeometry()
        # Center the window in that screen's available area
        self.move(r.center() - self.rect().center())

    # ----------------- Export handler ----------------- #
    @Slot()
    def _export(self):
        warning_title = strings._("unencrypted_export")
        warning_message = strings._("unencrypted_export_warning")
        dlg = QMessageBox()
        dlg.setWindowTitle(warning_title)
        dlg.setText(warning_message)
        dlg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dlg.setIcon(QMessageBox.Warning)
        dlg.show()
        dlg.adjustSize()
        if dlg.exec() != QMessageBox.Yes:
            return False

        filters = (
            "JSON (*.json);;"
            "CSV (*.csv);;"
            "HTML (*.html);;"
            "Markdown (*.md);;"
            "SQL (*.sql);;"
        )

        start_dir = os.path.join(os.path.expanduser("~"), "Documents")
        filename, selected_filter = QFileDialog.getSaveFileName(
            self, strings._("export_entries"), start_dir, filters
        )
        if not filename:
            return  # user cancelled

        default_ext = {
            "JSON (*.json)": ".json",
            "CSV (*.csv)": ".csv",
            "HTML (*.html)": ".html",
            "Markdown (*.md)": ".md",
            "SQL (*.sql)": ".sql",
        }.get(selected_filter, ".md")

        if not Path(filename).suffix:
            filename += default_ext

        try:
            entries = self.db.get_all_entries()
            if selected_filter.startswith("JSON"):
                self.db.export_json(entries, filename)
            elif selected_filter.startswith("CSV"):
                self.db.export_csv(entries, filename)
            elif selected_filter.startswith("HTML"):
                self.db.export_html(entries, filename)
            elif selected_filter.startswith("Markdown"):
                self.db.export_markdown(entries, filename)
            elif selected_filter.startswith("SQL"):
                self.db.export_sql(filename)
            else:
                raise ValueError(strings._("unrecognised_extension"))

            QMessageBox.information(
                self,
                strings._("export_complete"),
                strings._("saved_to") + f" {filename}",
            )
        except Exception as e:
            QMessageBox.critical(self, strings._("export_failed"), str(e))

    # ----------------- Backup handler ----------------- #
    @Slot()
    def _backup(self):
        filters = "SQLCipher (*.db);;"

        now = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        start_dir = os.path.join(
            os.path.expanduser("~"), "Documents", f"bouquin_backup_{now}.db"
        )
        filename, selected_filter = QFileDialog.getSaveFileName(
            self, strings._("backup_encrypted_notebook"), start_dir, filters
        )
        if not filename:
            return  # user cancelled

        default_ext = {
            "SQLCipher (*.db)": ".db",
        }.get(selected_filter, ".db")

        if not Path(filename).suffix:
            filename += default_ext

        try:
            if selected_filter.startswith("SQL"):
                self.db.export_sqlcipher(filename)
                QMessageBox.information(
                    self,
                    strings._("backup_complete"),
                    strings._("saved_to") + f" {filename}",
                )
        except Exception as e:
            QMessageBox.critical(self, strings._("backup_failed"), str(e))

    # ----------------- Help handlers ----------------- #

    def _open_docs(self):
        url_str = "https://git.mig5.net/mig5/bouquin/wiki/Help"
        url = QUrl.fromUserInput(url_str)
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self,
                strings._("documentation"),
                strings._("couldnt_open") + url.toDisplayString(),
            )

    def _open_bugs(self):
        dlg = BugReportDialog(self)
        dlg.exec()

    def _open_version(self):
        self.version_checker.show_version_dialog()

    # ----------------- Idle handlers ----------------- #
    def _apply_idle_minutes(self, minutes: int):
        minutes = max(0, int(minutes))
        if not hasattr(self, "_idle_timer"):
            return
        if minutes == 0:
            self._idle_timer.stop()
            # If currently locked, unlock when user disables the timer:
            if getattr(self, "_locked", False):
                self._locked = False
                if hasattr(self, "_lock_overlay"):
                    self._lock_overlay.hide()
        else:
            self._idle_timer.setInterval(minutes * 60 * 1000)
            if not getattr(self, "_locked", False):
                self._idle_timer.start()

    def eventFilter(self, obj, event):
        # Catch right-clicks on calendar BEFORE selectionChanged can fire
        if obj == self.calendar and event.type() == QEvent.MouseButtonPress:
            # QMouseEvent in PySide6
            if event.button() == Qt.RightButton:
                self._showing_context_menu = True

        if event.type() == QEvent.KeyPress and not self._locked:
            self._idle_timer.start()

        if event.type() in (QEvent.ApplicationActivate, QEvent.WindowActivate):
            QTimer.singleShot(0, self._focus_editor_now)

        return super().eventFilter(obj, event)

    def _enter_lock(self):
        """
        Trigger the lock overlay and disable widgets
        """
        if self._locked:
            return
        self._locked = True
        if self.menuBar():
            self.menuBar().setEnabled(False)
        if self.statusBar():
            self.statusBar().setEnabled(False)
            self.statusBar().hide()
        tb = getattr(self, "toolBar", None)
        if tb:
            tb.setEnabled(False)
            tb.hide()
        self._lock_overlay.show()
        self._lock_overlay.raise_()
        lock_msg = strings._("lock_overlay_locked")
        self.setWindowTitle(f"{APP_NAME} ({lock_msg})")

    @Slot()
    def _on_unlock_clicked(self):
        """
        Prompt for key to unlock screen
        If successful, re-enable widgets
        """
        try:
            ok = self._prompt_for_key_until_valid(first_time=False)
        except Exception as e:
            QMessageBox.critical(self, strings._("unlock_failed"), str(e))
            return
        if ok:
            self._locked = False
            self._lock_overlay.hide()
            if self.menuBar():
                self.menuBar().setEnabled(True)
            if self.statusBar():
                self.statusBar().setEnabled(True)
                self.statusBar().show()
            tb = getattr(self, "toolBar", None)
            if tb:
                tb.setEnabled(True)
                tb.show()
            self._idle_timer.start()
            QTimer.singleShot(0, self._focus_editor_now)
            self.setWindowTitle(APP_NAME)

    # ----------------- Close handlers ----------------- #
    def closeEvent(self, event):
        # Persist geometry if settings exist (window might be half-initialized).
        if getattr(self, "settings", None) is not None:
            try:
                self.settings.setValue("main/geometry", self.saveGeometry())
                self.settings.setValue("main/windowState", self.saveState())
                self.settings.setValue("main/maximized", self.isMaximized())
            except Exception:
                pass

        # Stop timers if present to avoid late autosaves firing during teardown.
        for _t in ("_autosave_timer", "_idle_timer"):
            t = getattr(self, _t, None)
            if t:
                t.stop()

        # Save content from tabs if the database is still connected
        db = getattr(self, "db", None)
        conn = getattr(db, "conn", None)
        tw = getattr(self, "tab_widget", None)
        if db is not None and conn is not None and tw is not None:
            try:
                for i in range(tw.count()):
                    editor = tw.widget(i)
                    if editor is not None:
                        self._save_editor_content(editor)
            except Exception:
                # Don't let teardown crash if one tab fails to save.
                pass
            try:
                db.close()
            except Exception:
                pass

        super().closeEvent(event)

    # ----------------- Below logic helps focus the editor ----------------- #

    def _focus_editor_now(self):
        """Give focus to the editor and ensure the caret is visible."""
        if getattr(self, "_locked", False):
            return
        if not self.isActiveWindow():
            return
        # Belt-and-suspenders: do it now and once more on the next tick
        self.editor.setFocus(Qt.ActiveWindowFocusReason)
        self.editor.ensureCursorVisible()
        QTimer.singleShot(
            0,
            lambda: (
                (
                    self.editor.setFocus(Qt.ActiveWindowFocusReason)
                    if self.editor
                    else None
                ),
                self.editor.ensureCursorVisible() if self.editor else None,
            ),
        )

    def _on_app_state_changed(self, state):
        # Called on macOS/Wayland/Windows when the whole app re-activates
        if state == Qt.ApplicationActive and self.isActiveWindow():
            QTimer.singleShot(0, self._focus_editor_now)

    def changeEvent(self, ev):
        # Called on some platforms when the window's activation state flips
        super().changeEvent(ev)
        if ev.type() == QEvent.ActivationChange and self.isActiveWindow():
            QTimer.singleShot(0, self._focus_editor_now)
