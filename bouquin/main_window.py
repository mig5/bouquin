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
    QPalette,
    QTextCharFormat,
    QTextCursor,
    QTextListFormat,
)
from PySide6.QtWidgets import (
    QApplication,
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
from .toolbar import ToolBar
from .theme import Theme, ThemeManager


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

        # Toolbar for controlling styling
        self.toolBar = ToolBar()
        self.addToolBar(self.toolBar)
        self._bind_toolbar()

        # Create the first editor tab
        self._create_new_tab()

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
        self._lock_overlay = LockOverlay(self.centralWidget(), self._on_unlock_clicked)
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
        self.statusBar().showMessage("Ready", 800)
        # Add findBar and add it to the statusBar
        # FindBar will get the current editor dynamically via a callable
        self.findBar = FindBar(
            lambda: self.current_editor(), shortcut_parent=self, parent=self
        )
        self.statusBar().addPermanentWidget(self.findBar)
        # When the findBar closes, put the caret back in the editor
        self.findBar.closed.connect(self._focus_editor_now)

        # Menu bar (File)
        mb = self.menuBar()
        file_menu = mb.addMenu("&File")
        act_save = QAction("&Save a version", self)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(lambda: self._save_current(explicit=True))
        file_menu.addAction(act_save)
        act_history = QAction("History", self)
        act_history.setShortcut("Ctrl+H")
        act_history.setShortcutContext(Qt.ApplicationShortcut)
        act_history.triggered.connect(self._open_history)
        file_menu.addAction(act_history)
        act_settings = QAction("Settin&gs", self)
        act_settings.setShortcut("Ctrl+G")
        act_settings.triggered.connect(self._open_settings)
        file_menu.addAction(act_settings)
        act_export = QAction("&Export", self)
        act_export.setShortcut("Ctrl+E")
        act_export.triggered.connect(self._export)
        file_menu.addAction(act_export)
        act_backup = QAction("&Backup", self)
        act_backup.setShortcut("Ctrl+Shift+B")
        act_backup.triggered.connect(self._backup)
        file_menu.addAction(act_backup)
        file_menu.addSeparator()
        act_quit = QAction("&Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        # Navigate menu with next/previous/today
        nav_menu = mb.addMenu("&Navigate")
        act_prev = QAction("Previous Day", self)
        act_prev.setShortcut("Ctrl+Shift+P")
        act_prev.setShortcutContext(Qt.ApplicationShortcut)
        act_prev.triggered.connect(lambda: self._adjust_day(-1))
        nav_menu.addAction(act_prev)
        self.addAction(act_prev)

        act_next = QAction("Next Day", self)
        act_next.setShortcut("Ctrl+Shift+N")
        act_next.setShortcutContext(Qt.ApplicationShortcut)
        act_next.triggered.connect(lambda: self._adjust_day(1))
        nav_menu.addAction(act_next)
        self.addAction(act_next)

        act_today = QAction("Today", self)
        act_today.setShortcut("Ctrl+Shift+T")
        act_today.setShortcutContext(Qt.ApplicationShortcut)
        act_today.triggered.connect(self._adjust_today)
        nav_menu.addAction(act_today)
        self.addAction(act_today)

        act_find = QAction("Find on page", self)
        act_find.setShortcut(QKeySequence.Find)
        act_find.triggered.connect(self.findBar.show_bar)
        nav_menu.addAction(act_find)
        self.addAction(act_find)

        act_find_next = QAction("Find Next", self)
        act_find_next.setShortcut(QKeySequence.FindNext)
        act_find_next.triggered.connect(self.findBar.find_next)
        nav_menu.addAction(act_find_next)
        self.addAction(act_find_next)

        act_find_prev = QAction("Find Previous", self)
        act_find_prev.setShortcut(QKeySequence.FindPrevious)
        act_find_prev.triggered.connect(self.findBar.find_prev)
        nav_menu.addAction(act_find_prev)
        self.addAction(act_find_prev)

        # Help menu with drop-down
        help_menu = mb.addMenu("&Help")
        act_docs = QAction("Documentation", self)
        act_docs.setShortcut("Ctrl+D")
        act_docs.setShortcutContext(Qt.ApplicationShortcut)
        act_docs.triggered.connect(self._open_docs)
        help_menu.addAction(act_docs)
        self.addAction(act_docs)
        act_bugs = QAction("Report a bug", self)
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

        self._apply_link_css()  # Apply link color on startup
        # re-apply all runtime color tweaks when theme changes
        self.themes.themeChanged.connect(lambda _t: self._retheme_overrides())
        self.themes.themeChanged.connect(self._apply_calendar_theme)
        self._apply_calendar_text_colors()
        self._apply_calendar_theme(self.themes.current())

        # apply once on startup so links / calendar colors are set immediately
        self._retheme_overrides()

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

    def _prompt_for_key_until_valid(self, first_time: bool) -> bool:
        """
        Prompt for the SQLCipher key.
        """
        if first_time:
            title = "Set an encryption key"
            message = "Bouquin encrypts your data.\n\nPlease create a strong passphrase to encrypt the notebook.\n\nYou can always change it later!"
        else:
            title = "Unlock encrypted notebook"
            message = "Enter your key to unlock the notebook"
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
        self._load_date_into_editor(date, editor)

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

        self.tab_widget.removeTab(index)

    def _on_tab_changed(self, index: int):
        """Handle tab change - reconnect toolbar and sync UI."""
        if index < 0:
            return

        editor = self.tab_widget.widget(index)
        if editor and hasattr(editor, "current_date"):
            # Update calendar selection to match the tab
            with QSignalBlocker(self.calendar):
                self.calendar.setSelectedDate(editor.current_date)

        # Reconnect toolbar to new active editor
        self._sync_toolbar()

        # Focus the editor
        QTimer.singleShot(0, self._focus_editor_now)

    def _call_editor(self, method_name, *args):
        """
        Call the relevant method of the MarkdownEditor class on bind
        """
        ed = self.current_editor()
        if ed is None:
            return
        getattr(ed, method_name)(*args)

    def current_editor(self) -> MarkdownEditor | None:
        """Get the currently active editor."""
        return self.tab_widget.currentWidget()

    @property
    def editor(self) -> MarkdownEditor | None:
        """Compatibility property to get current editor (for existing code)."""
        return self.current_editor()

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
        open_in_new_tab_action = menu.addAction("Open in New Tab")
        action = menu.exec_(self.calendar.mapToGlobal(pos))

        self._showing_context_menu = False

        if action == open_in_new_tab_action and clicked_date and clicked_date.isValid():
            self._open_date_in_tab(clicked_date)

    # ----------------- Some theme helpers -------------------#
    def _retheme_overrides(self):
        if hasattr(self, "_lock_overlay"):
            self._lock_overlay._apply_overlay_style()
        self._apply_calendar_text_colors()
        self._apply_link_css()
        self._apply_search_highlights(getattr(self, "_search_highlighted_dates", set()))
        self.calendar.update()
        self.editor.viewport().update()

    def _apply_link_css(self):
        if self.themes and self.themes.current() == Theme.DARK:
            anchor = Theme.ORANGE_ANCHOR.value
            visited = Theme.ORANGE_ANCHOR_VISITED.value
            css = f"""
                a {{ color: {anchor}; text-decoration: underline; }}
                a:visited {{ color: {visited}; }}
            """
        else:
            css = ""  # Default to no custom styling for links (system or light theme)

        try:
            self.editor.document().setDefaultStyleSheet(css)
        except Exception:
            pass

        try:
            self.search.document().setDefaultStyleSheet(css)
        except Exception:
            pass

    def _apply_calendar_theme(self, theme: Theme):
        """Use orange accents on the calendar in dark mode only."""
        app_pal = QApplication.instance().palette()

        if theme == Theme.DARK:
            highlight = QColor(Theme.ORANGE_ANCHOR.value)
            black = QColor(0, 0, 0)

            highlight_css = Theme.ORANGE_ANCHOR.value

            # Per-widget palette: selection color inside the date grid
            pal = self.calendar.palette()
            pal.setColor(QPalette.Highlight, highlight)
            pal.setColor(QPalette.HighlightedText, black)
            self.calendar.setPalette(pal)

            # Stylesheet: nav bar + selected-day background
            self.calendar.setStyleSheet(
                f"""
                QWidget#qt_calendar_navigationbar {{ background-color: {highlight_css}; }}
                QCalendarWidget QToolButton {{ color: black; }}
                QCalendarWidget QToolButton:hover {{ background-color: rgba(255,165,0,0.20); }}
                /* Selected day color in the table view */
                QCalendarWidget QTableView:enabled {{
                    selection-background-color: {highlight_css};
                    selection-color: black;
                }}
                /* Optional: keep weekday header readable */
                QCalendarWidget QTableView QHeaderView::section {{
                    background: transparent;
                    color: palette(windowText);
                }}
            """
            )
        else:
            # Back to app defaults in light/system
            self.calendar.setPalette(app_pal)
            self.calendar.setStyleSheet("")

        self._apply_calendar_text_colors()
        self.calendar.update()

    def _apply_calendar_text_colors(self):
        pal = self.palette()
        txt = pal.windowText().color()
        fmt = QTextCharFormat()
        fmt.setForeground(txt)
        # Use normal text color for weekends
        self.calendar.setWeekdayTextFormat(Qt.Saturday, fmt)
        self.calendar.setWeekdayTextFormat(Qt.Sunday, fmt)

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
        try:
            for date_iso in self.db.dates_with_content():
                qd = QDate.fromString(date_iso, "yyyy-MM-dd")
                if qd.isValid():
                    fmt = self.calendar.dateTextFormat(qd)
                    fmt.setFontWeight(QFont.Weight.Bold)  # add bold only
                    self.calendar.setDateTextFormat(qd, fmt)
                    self._marked_dates.add(qd)
        except Exception:
            pass

    # --- UI handlers ---------------------------------------------------------

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

        # these aren’t editor methods
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

    def _load_selected_date(self, date_iso=False, extra_data=False):
        """Load a date into the current editor"""
        editor = self.current_editor()
        if not editor:
            return

        if not date_iso:
            date_iso = self._current_date_iso()

        qd = QDate.fromString(date_iso, "yyyy-MM-dd")
        self._load_date_into_editor(qd, editor, extra_data)
        editor.current_date = qd

        # Update tab title
        current_index = self.tab_widget.currentIndex()
        if current_index >= 0:
            self.tab_widget.setTabText(current_index, date_iso)

        # Keep tabs sorted by date
        self._reorder_tabs_by_date()

    def _load_date_into_editor(
        self, date: QDate, editor: MarkdownEditor, extra_data=False
    ):
        """Load a specific date's content into a given editor."""
        date_iso = date.toString("yyyy-MM-dd")
        try:
            text = self.db.get_entry(date_iso)
            if extra_data:
                # Append extra data as markdown
                if text and not text.endswith("\n"):
                    text += "\n"
                text += extra_data
                # Force a save now so we don't lose it.
                self._set_editor_markdown_preserve_view(text, editor)
                self._dirty = True
                self._save_date(date_iso, True)
        except Exception as e:
            QMessageBox.critical(self, "Read Error", str(e))
            return

        self._set_editor_markdown_preserve_view(text, editor)
        self._dirty = False

    def _save_editor_content(self, editor: MarkdownEditor):
        """Save a specific editor's content to its associated date."""
        if not hasattr(editor, "current_date"):
            return
        date_iso = editor.current_date.toString("yyyy-MM-dd")
        try:
            md = editor.to_markdown()
            self.db.save_new_version(date_iso, md, note="autosave")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

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
        try:
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
                    "Unchecked checkbox items moved to next day",
                )

                # Join unchecked items into markdown format
                unchecked_str = "\n".join(unchecked_items) + "\n"

                # Load the unchecked items into the current editor
                self._load_selected_date(False, unchecked_str)
            else:
                return False

        except Exception as e:
            raise SystemError(e)

    def _on_date_changed(self):
        """
        When the calendar selection changes, save the previous day's note if dirty,
        so we don't lose that text, then load the newly selected day into current tab.
        """
        # Skip if we're showing a context menu (right-click shouldn't load dates)
        if getattr(self, "_showing_context_menu", False):
            return

        editor = self.current_editor()
        if not editor:
            return

        # Stop pending autosave and persist current buffer if needed
        try:
            self._save_timer.stop()
        except Exception:
            pass

        # Save the current editor's content if dirty
        if hasattr(editor, "current_date") and self._dirty:
            prev_date_iso = editor.current_date.toString("yyyy-MM-dd")
            self._save_date(prev_date_iso, explicit=False)

        # Now load the newly selected date into the current tab
        new_date = self.calendar.selectedDate()
        self._load_date_into_editor(new_date, editor)
        editor.current_date = new_date

        # Update tab title
        current_index = self.tab_widget.currentIndex()
        if current_index >= 0:
            self.tab_widget.setTabText(current_index, new_date.toString("yyyy-MM-dd"))

        # Keep tabs sorted by date
        self._reorder_tabs_by_date()

    # ----------- History handler ------------#
    def _open_history(self):
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
            "Insert image(s)",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
        )
        if not paths:
            return
        # Insert each image
        for path_str in paths:
            self.editor.insert_image_from_path(Path(path_str))

    # --------------- Database saving of content ---------------- #
    def _save_date(self, date_iso: str, explicit: bool = False, note: str = "autosave"):
        """
        Save editor contents into the given date. Shows status on success.
        explicit=True means user invoked Save: show feedback even if nothing changed.
        """
        if not self._dirty and not explicit:
            return
        text = self.editor.to_markdown()
        try:
            self.db.save_new_version(date_iso, text, note)
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
        """Save the current editor's content."""
        try:
            self._save_timer.stop()
        except Exception:
            pass

        editor = self.current_editor()
        if not editor or not hasattr(editor, "current_date"):
            return

        if explicit:
            # Prompt for a note
            dlg = SaveDialog(self)
            if dlg.exec() != QDialog.Accepted:
                return
            note = dlg.note_text()
        else:
            note = "autosave"
        # Save the current editor's date
        date_iso = editor.current_date.toString("yyyy-MM-dd")
        self._save_date(date_iso, explicit, note)
        try:
            self._save_timer.start()
        except Exception:
            pass

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

        # Persist once
        save_db_config(self.cfg)

        # Apply idle setting immediately (restart the timer with new interval if it changed)
        self._apply_idle_minutes(self.cfg.idle_minutes)

        # If the DB path changed, reconnect
        if self.cfg.path != old_path:
            self.db.close()
            if not self._prompt_for_key_until_valid(first_time=False):
                QMessageBox.warning(
                    self, "Reopen failed", "Could not unlock database at new path."
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
        warning_title = "Unencrypted export"
        warning_message = """
Exporting the database will be unencrypted!

Are you sure you want to continue?

If you want an encrypted backup, choose Backup instead of Export.
"""
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
            self, "Export entries", start_dir, filters
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
                raise ValueError("Unrecognised extension!")

            QMessageBox.information(self, "Export complete", f"Saved to:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    # ----------------- Backup handler ----------------- #
    @Slot()
    def _backup(self):
        filters = "SQLCipher (*.db);;"

        now = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        start_dir = os.path.join(
            os.path.expanduser("~"), "Documents", f"bouquin_backup_{now}.db"
        )
        filename, selected_filter = QFileDialog.getSaveFileName(
            self, "Backup encrypted notebook", start_dir, filters
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
                    self, "Backup complete", f"Saved to:\n{filename}"
                )
        except Exception as e:
            QMessageBox.critical(self, "Backup failed", str(e))

    # ----------------- Help handlers ----------------- #

    def _open_docs(self):
        url_str = "https://git.mig5.net/mig5/bouquin/wiki/Help"
        url = QUrl.fromUserInput(url_str)
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self, "Open Documentation", f"Couldn't open:\n{url.toDisplayString()}"
            )

    def _open_bugs(self):
        url_str = "https://nr.mig5.net/forms/mig5/contact"
        url = QUrl.fromUserInput(url_str)
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self, "Open Documentation", f"Couldn't open:\n{url.toDisplayString()}"
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
                try:
                    self._locked = False
                    if hasattr(self, "_lock_overlay"):
                        self._lock_overlay.hide()
                except Exception:
                    pass
        else:
            self._idle_timer.setInterval(minutes * 60 * 1000)
            if not getattr(self, "_locked", False):
                self._idle_timer.start()

    def eventFilter(self, obj, event):
        # Catch right-clicks on calendar BEFORE selectionChanged can fire
        if obj == self.calendar and event.type() == QEvent.MouseButtonPress:
            try:
                # QMouseEvent in PySide6
                if event.button() == Qt.RightButton:
                    self._showing_context_menu = True
            except Exception:
                pass

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
        tb = getattr(self, "toolBar", None)
        if tb:
            tb.setEnabled(False)
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
            QMessageBox.critical(self, "Unlock failed", str(e))
            return
        if ok:
            self._locked = False
            self._lock_overlay.hide()
            if self.menuBar():
                self.menuBar().setEnabled(True)
            if self.statusBar():
                self.statusBar().setEnabled(True)
            tb = getattr(self, "toolBar", None)
            if tb:
                tb.setEnabled(True)
            self._idle_timer.start()
            QTimer.singleShot(0, self._focus_editor_now)

    # ----------------- Close handlers ----------------- #
    def closeEvent(self, event):
        try:
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
        editor = self.current_editor()
        if not editor:
            return
        # Belt-and-suspenders: do it now and once more on the next tick
        editor.setFocus(Qt.ActiveWindowFocusReason)
        editor.ensureCursorVisible()
        QTimer.singleShot(
            0,
            lambda: (
                editor.setFocus(Qt.ActiveWindowFocusReason) if editor else None,
                editor.ensureCursorVisible() if editor else None,
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

    def _set_editor_markdown_preserve_view(
        self, markdown: str, editor: MarkdownEditor | None = None
    ):
        if editor is None:
            editor = self.current_editor()
        if not editor:
            return

        ed = editor

        # Save caret/selection and scroll
        cur = ed.textCursor()
        old_pos, old_anchor = cur.position(), cur.anchor()
        v = ed.verticalScrollBar().value()
        h = ed.horizontalScrollBar().value()

        # Only touch the doc if it actually changed
        ed.blockSignals(True)
        if ed.to_markdown() != markdown:
            ed.from_markdown(markdown)
        ed.blockSignals(False)

        # Restore scroll first
        ed.verticalScrollBar().setValue(v)
        ed.horizontalScrollBar().setValue(h)

        # Restore caret/selection (bounded to new doc length)
        doc_length = ed.document().characterCount() - 1
        old_pos = min(old_pos, doc_length)
        old_anchor = min(old_anchor, doc_length)

        cur = ed.textCursor()
        cur.setPosition(old_anchor)
        mode = (
            QTextCursor.KeepAnchor if old_anchor != old_pos else QTextCursor.MoveAnchor
        )
        cur.setPosition(old_pos, mode)
        ed.setTextCursor(cur)

        # Refresh highlights if the theme changed
        if hasattr(self, "findBar"):
            self.findBar.refresh()
