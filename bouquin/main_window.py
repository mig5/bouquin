from __future__ import annotations

import datetime
import os
import sys
import re

from pathlib import Path
from PySide6.QtCore import (
    QDate,
    QTimer,
    Qt,
    QSettings,
    Slot,
    QUrl,
    QEvent,
    QSignalBlocker,
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
    QTextCharFormat,
    QTextCursor,
    QTextListFormat,
)
from PySide6.QtWidgets import (
    QCalendarWidget,
    QDialog,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .db import DBManager
from .markdown_editor import MarkdownEditor
from .find_bar import FindBar
from .history_dialog import HistoryDialog
from .key_prompt import KeyPrompt
from .lock_overlay import LockOverlay
from .save_dialog import SaveDialog
from .search import Search
from .settings import APP_ORG, APP_NAME, load_db_config, save_db_config
from .settings_dialog import SettingsDialog
from . import strings
from .toolbar import ToolBar
from .theme import ThemeManager


class MainWindow(QMainWindow):
    def __init__(self, themes: ThemeManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 650)

        self.themes = themes  # Store the themes manager

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

        # ---- UI: Left fixed panel (calendar) + right editor -----------------
        self.calendar = QCalendarWidget()
        self.calendar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.calendar.setGridVisible(True)
        self.calendar.selectionChanged.connect(self._on_date_changed)
        self.themes.register_calendar(self.calendar)

        self.search = Search(self.db)
        self.search.openDateRequested.connect(self._load_selected_date)
        self.search.resultDatesChanged.connect(self._on_search_dates_changed)

        # Lock the calendar to the left panel at the top to stop it stretching
        # when the main window is resized.
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.addWidget(self.calendar)
        left_layout.addWidget(self.search)
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
        from PySide6.QtWidgets import QApplication

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
        act_history.setShortcut("Ctrl+H")
        act_history.setShortcutContext(Qt.ApplicationShortcut)
        act_history.triggered.connect(self._open_history)
        file_menu.addAction(act_history)
        act_settings = QAction(strings._("main_window_settings_accessible_flag"), self)
        act_settings.setShortcut("Ctrl+G")
        act_settings.triggered.connect(self._open_settings)
        file_menu.addAction(act_settings)
        act_export = QAction(strings._("export_accessible_flag"), self)
        act_export.setShortcut("Ctrl+E")
        act_export.triggered.connect(self._export)
        file_menu.addAction(act_export)
        act_backup = QAction("&" + strings._("backup"), self)
        act_backup.setShortcut("Ctrl+Shift+B")
        act_backup.triggered.connect(self._backup)
        file_menu.addAction(act_backup)
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
        act_docs.setShortcut("Ctrl+D")
        act_docs.setShortcutContext(Qt.ApplicationShortcut)
        act_docs.triggered.connect(self._open_docs)
        help_menu.addAction(act_docs)
        self.addAction(act_docs)
        act_bugs = QAction(strings._("report_a_bug"), self)
        act_bugs.setShortcut("Ctrl+R")
        act_bugs.setShortcutContext(Qt.ApplicationShortcut)
        act_bugs.triggered.connect(self._open_bugs)
        help_menu.addAction(act_bugs)
        self.addAction(act_bugs)

        # Autosave
        self._dirty = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_current)
        # Note: textChanged will be connected per-editor in _create_new_tab

        # First load + mark dates in calendar with content
        if not self._load_yesterday_todos():
            self._load_selected_date()
        self._refresh_calendar_marks()

        # Restore window position from settings
        self.settings = QSettings(APP_ORG, APP_NAME)
        self._restore_window_position()

        # re-apply all runtime color tweaks when theme changes
        self.themes.themeChanged.connect(lambda _t: self._retheme_overrides())
        self._apply_calendar_text_colors()

        # apply once on startup so links / calendar colors are set immediately
        self._retheme_overrides()

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
        except Exception as e:
            if str(e) == "file is not a database":
                error = strings._("db_key_incorrect")
            else:
                error = str(e)
            QMessageBox.critical(self, strings._("db_database_error"), error)
            return False
        return ok

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
            dlg = KeyPrompt(self, title, message)
            if dlg.exec() != QDialog.Accepted:
                return False
            self.cfg.key = dlg.key()
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
            # keep calendar selection in sync (don’t trigger load)
            from PySide6.QtCore import QSignalBlocker

            with QSignalBlocker(self.calendar):
                self.calendar.setSelectedDate(date)
            QTimer.singleShot(0, self._focus_editor_now)
            return self.tab_widget.widget(idx)
        # not open yet -> create
        return self._create_new_tab(date)

    def _create_new_tab(self, date: QDate | None = None) -> MarkdownEditor:
        if date is None:
            date = self.calendar.selectedDate()

        # Deduplicate: if already open, just jump there
        existing = self._tab_index_for_date(date)
        if existing != -1:
            self.tab_widget.setCurrentIndex(existing)
            return self.tab_widget.widget(existing)

        """Create a new editor tab and return the editor instance."""
        editor = MarkdownEditor(self.themes)

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
        # Keep calendar in sync
        with QSignalBlocker(self.calendar):
            self.calendar.setSelectedDate(qd)

        self._load_date_into_editor(qd, extra_data)
        self.editor.current_date = qd

        # Update tab title
        current_index = self.tab_widget.currentIndex()
        if current_index >= 0:
            self.tab_widget.setTabText(current_index, date_iso)

        # Keep tabs sorted by date
        self._reorder_tabs_by_date()

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

    def _load_yesterday_todos(self):
        if not self.cfg.move_todos:
            return
        yesterday_str = QDate.currentDate().addDays(-1).toString("yyyy-MM-dd")
        text = self.db.get_entry(yesterday_str)
        unchecked_items = []

        # Split into lines and find unchecked checkbox items
        lines = text.split("\n")
        remaining_lines = []

        for line in lines:
            # Check for unchecked markdown checkboxes: - [ ] or - [☐]
            if re.match(r"^\s*-\s*\[\s*\]\s+", line) or re.match(
                r"^\s*-\s*\[☐\]\s+", line
            ):
                # Extract the text after the checkbox
                item_text = re.sub(r"^\s*-\s*\[[\s☐]\]\s+", "", line)
                unchecked_items.append(f"- [ ] {item_text}")
            else:
                # Keep all other lines
                remaining_lines.append(line)

        # Save modified content back if we moved items
        if unchecked_items:
            modified_text = "\n".join(remaining_lines)
            self.db.save_new_version(
                yesterday_str,
                modified_text,
                strings._("unchecked_checkbox_items_moved_to_next_day"),
            )

            # Join unchecked items into markdown format
            unchecked_str = "\n".join(unchecked_items) + "\n"

            # Load the unchecked items into the current editor
            self._load_selected_date(False, unchecked_str)
        else:
            return False

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

        # Now load the newly selected date into the current tab
        new_date = self.calendar.selectedDate()
        self._load_date_into_editor(new_date)
        self.editor.current_date = new_date

        # Update tab title
        current_index = self.tab_widget.currentIndex()
        if current_index >= 0:
            self.tab_widget.setTabText(current_index, new_date.toString("yyyy-MM-dd"))

        # Keep tabs sorted by date
        self._reorder_tabs_by_date()

    def _save_date(self, date_iso: str, explicit: bool = False, note: str = "autosave"):
        """
        Save editor contents into the given date. Shows status on success.
        explicit=True means user invoked Save: show feedback even if nothing changed.
        """
        if not self._dirty and not explicit:
            return
        text = self.editor.to_markdown()
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
    def _retheme_overrides(self):
        self._apply_calendar_text_colors()
        self._apply_search_highlights(getattr(self, "_search_highlighted_dates", set()))
        self.calendar.update()
        self.editor.viewport().update()

    def _apply_calendar_text_colors(self):
        pal = self.palette()
        txt = pal.windowText().color()
        fmt = QTextCharFormat()
        fmt.setForeground(txt)
        # Use normal text color for weekends
        self.calendar.setWeekdayTextFormat(Qt.Saturday, fmt)
        self.calendar.setWeekdayTextFormat(Qt.Sunday, fmt)

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

        tb.boldRequested.connect(self._tb_bold)
        tb.italicRequested.connect(self._tb_italic)
        tb.strikeRequested.connect(self._tb_strike)
        tb.codeRequested.connect(self._tb_code)
        tb.headingRequested.connect(self._tb_heading)
        tb.bulletsRequested.connect(self._tb_bullets)
        tb.numbersRequested.connect(self._tb_numbers)
        tb.checkboxesRequested.connect(self._tb_checkboxes)

        tb.historyRequested.connect(self._open_history)
        tb.insertImageRequested.connect(self._on_insert_image)

        self._toolbar_bound = True

    def _sync_toolbar(self):
        fmt = self.editor.currentCharFormat()
        c = self.editor.textCursor()

        # Block signals so setChecked() doesn't re-trigger actions
        QSignalBlocker(self.toolBar.actBold)
        QSignalBlocker(self.toolBar.actItalic)
        QSignalBlocker(self.toolBar.actStrike)

        self.toolBar.actBold.setChecked(fmt.fontWeight() == QFont.Weight.Bold)
        self.toolBar.actItalic.setChecked(fmt.fontItalic())
        self.toolBar.actStrike.setChecked(fmt.fontStrikeOut())

        # Headings: decide which to check by current point size
        def _approx(a, b, eps=0.5):  # small float tolerance
            return abs(float(a) - float(b)) <= eps

        cur_size = fmt.fontPointSize() or self.editor.font().pointSizeF()

        bH1 = _approx(cur_size, 24)
        bH2 = _approx(cur_size, 18)
        bH3 = _approx(cur_size, 14)

        QSignalBlocker(self.toolBar.actH1)
        QSignalBlocker(self.toolBar.actH2)
        QSignalBlocker(self.toolBar.actH3)
        QSignalBlocker(self.toolBar.actNormal)

        self.toolBar.actH1.setChecked(bH1)
        self.toolBar.actH2.setChecked(bH2)
        self.toolBar.actH3.setChecked(bH3)
        self.toolBar.actNormal.setChecked(not (bH1 or bH2 or bH3))

        # Lists
        lst = c.currentList()
        bullets_on = lst and lst.format().style() == QTextListFormat.Style.ListDisc
        numbers_on = lst and lst.format().style() == QTextListFormat.Style.ListDecimal
        QSignalBlocker(self.toolBar.actBullets)
        QSignalBlocker(self.toolBar.actNumbers)
        self.toolBar.actBullets.setChecked(bool(bullets_on))
        self.toolBar.actNumbers.setChecked(bool(numbers_on))

    # ----------- History handler ------------#
    def _open_history(self):
        if hasattr(self.editor, "current_date"):
            date_iso = self.editor.current_date.toString("yyyy-MM-dd")
        else:
            date_iso = self._current_date_iso()

        dlg = HistoryDialog(self.db, date_iso, self)
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
        self.cfg.locale = getattr(new_cfg, "locale", self.cfg.locale)

        # Persist once
        save_db_config(self.cfg)

        # Apply idle setting immediately (restart the timer with new interval if it changed)
        self._apply_idle_minutes(self.cfg.idle_minutes)

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
            "Text (*.txt);;"
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
            "Text (*.txt)": ".txt",
            "JSON (*.json)": ".json",
            "CSV (*.csv)": ".csv",
            "HTML (*.html)": ".html",
            "Markdown (*.md)": ".md",
            "SQL (*.sql)": ".sql",
        }.get(selected_filter, ".txt")

        if not Path(filename).suffix:
            filename += default_ext

        try:
            entries = self.db.get_all_entries()
            if selected_filter.startswith("Text"):
                self.db.export_txt(entries, filename)
            elif selected_filter.startswith("JSON"):
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
        url_str = "https://nr.mig5.net/forms/mig5/contact"
        url = QUrl.fromUserInput(url_str)
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self,
                strings._("report_a_bug"),
                strings._("couldnt_open") + url.toDisplayString(),
            )

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

    # ----------------- Close handlers ----------------- #
    def closeEvent(self, event):
        # Save window position
        self.settings.setValue("main/geometry", self.saveGeometry())
        self.settings.setValue("main/windowState", self.saveState())
        self.settings.setValue("main/maximized", self.isMaximized())

        # Ensure we save all tabs before closing
        for i in range(self.tab_widget.count()):
            editor = self.tab_widget.widget(i)
            if editor:
                self._save_editor_content(editor)
        self.db.close()
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
