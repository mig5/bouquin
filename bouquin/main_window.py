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
    QPalette,
    QTextCharFormat,
    QTextListFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QDialog,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .db import DBManager
from .editor import Editor
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

        # This is the note-taking editor
        self.editor = Editor(self.themes)

        # Toolbar for controlling styling
        self.toolBar = ToolBar()
        self.addToolBar(self.toolBar)
        # Wire toolbar intents to editor methods
        self.toolBar.boldRequested.connect(self.editor.apply_weight)
        self.toolBar.italicRequested.connect(self.editor.apply_italic)
        self.toolBar.underlineRequested.connect(self.editor.apply_underline)
        self.toolBar.strikeRequested.connect(self.editor.apply_strikethrough)
        self.toolBar.codeRequested.connect(self.editor.apply_code)
        self.toolBar.headingRequested.connect(self.editor.apply_heading)
        self.toolBar.bulletsRequested.connect(self.editor.toggle_bullets)
        self.toolBar.numbersRequested.connect(self.editor.toggle_numbers)
        self.toolBar.checkboxesRequested.connect(self.editor.toggle_checkboxes)
        self.toolBar.alignRequested.connect(self.editor.setAlignment)
        self.toolBar.historyRequested.connect(self._open_history)
        self.toolBar.insertImageRequested.connect(self._on_insert_image)

        self.editor.currentCharFormatChanged.connect(lambda _f: self._sync_toolbar())
        self.editor.cursorPositionChanged.connect(self._sync_toolbar)

        split = QSplitter()
        split.addWidget(left_panel)
        split.addWidget(self.editor)
        split.setStretchFactor(1, 1)  # editor grows

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

        # Status bar for feedback
        self.statusBar().showMessage("Ready", 800)

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
        self.editor.textChanged.connect(self._on_text_changed)

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

    def _retheme_overrides(self):
        if hasattr(self, "_lock_overlay"):
            self._lock_overlay._apply_overlay_style()
        self._apply_calendar_text_colors()
        self._apply_link_css()  # Reapply link styles based on the current theme
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
            # Apply to the editor (QTextEdit or any other relevant widgets)
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

        # Keep weekend text color in sync with the current palette
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

    def _sync_toolbar(self):
        fmt = self.editor.currentCharFormat()
        c = self.editor.textCursor()
        bf = c.blockFormat()

        # Block signals so setChecked() doesn't re-trigger actions
        QSignalBlocker(self.toolBar.actBold)
        QSignalBlocker(self.toolBar.actItalic)
        QSignalBlocker(self.toolBar.actUnderline)
        QSignalBlocker(self.toolBar.actStrike)

        self.toolBar.actBold.setChecked(fmt.fontWeight() == QFont.Weight.Bold)
        self.toolBar.actItalic.setChecked(fmt.fontItalic())
        self.toolBar.actUnderline.setChecked(fmt.fontUnderline())
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

        # Alignment
        align = bf.alignment() & Qt.AlignHorizontal_Mask
        QSignalBlocker(self.toolBar.actAlignL)
        self.toolBar.actAlignL.setChecked(align == Qt.AlignLeft)
        QSignalBlocker(self.toolBar.actAlignC)
        self.toolBar.actAlignC.setChecked(align == Qt.AlignHCenter)
        QSignalBlocker(self.toolBar.actAlignR)
        self.toolBar.actAlignR.setChecked(align == Qt.AlignRight)

    def _current_date_iso(self) -> str:
        d = self.calendar.selectedDate()
        return f"{d.year():04d}-{d.month():02d}-{d.day():02d}"

    def _load_selected_date(self, date_iso=False, extra_data=False):
        if not date_iso:
            date_iso = self._current_date_iso()
        try:
            text = self.db.get_entry(date_iso)
            if extra_data:
                # Wrap extra_data in a <p> tag for HTML rendering
                extra_data_html = f"<p>{extra_data}</p>"

                # Inject the extra_data before the closing </body></html>
                modified = re.sub(r"(<\/body><\/html>)", extra_data_html + r"\1", text)
                text = modified
                self.editor.setHtml(text)
                self._dirty = True
                self._save_date(date_iso, True)

        except Exception as e:
            QMessageBox.critical(self, "Read Error", str(e))
            return

        self.editor.blockSignals(True)
        self.editor.setHtml(text)
        self.editor.blockSignals(False)

        self._dirty = False
        # track which date the editor currently represents
        self._active_date_iso = date_iso
        qd = QDate.fromString(date_iso, "yyyy-MM-dd")
        self.calendar.setSelectedDate(qd)

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
        self.calendar.setSelectedDate(today)

    def _load_yesterday_todos(self):
        try:
            if not self.cfg.move_todos:
                return
            yesterday_str = QDate.currentDate().addDays(-1).toString("yyyy-MM-dd")
            text = self.db.get_entry(yesterday_str)
            unchecked_items = []

            # Regex to match the unchecked checkboxes and their associated text
            checkbox_pattern = re.compile(
                r"<span[^>]*>(☐)</span>\s*(.*?)</p>", re.DOTALL
            )

            # Find unchecked items and store them
            for match in checkbox_pattern.finditer(text):
                checkbox = match.group(1)  # Either ☐ or ☑
                item_text = match.group(2).strip()  # The text after the checkbox
                if checkbox == "☐":  # If it's an unchecked checkbox (☐)
                    unchecked_items.append("☐ " + item_text)  # Store the unchecked item

            # Remove the unchecked items from yesterday's HTML content
            if unchecked_items:
                # This regex will find the entire checkbox line and remove it from the HTML content
                uncheckbox_pattern = re.compile(
                    r"<span[^>]*>☐</span>\s*(.*?)</p>", re.DOTALL
                )
                modified_text = re.sub(
                    uncheckbox_pattern, "", text
                )  # Remove the checkbox lines

                # Save the modified HTML back to the database
                self.db.save_new_version(
                    yesterday_str,
                    modified_text,
                    "Unchecked checkbox items moved to next day",
                )

                # Join unchecked items into a formatted string
                unchecked_str = "\n".join(
                    [f"<p>{item}</p>" for item in unchecked_items]
                )

                # Load the unchecked items into the current editor
                self._load_selected_date(False, unchecked_str)
            else:
                return False

        except Exception as e:
            raise SystemError(e)

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

    def _save_date(self, date_iso: str, explicit: bool = False, note: str = "autosave"):
        """
        Save editor contents into the given date. Shows status on success.
        explicit=True means user invoked Save: show feedback even if nothing changed.
        """
        if not self._dirty and not explicit:
            return
        text = self.editor.to_html_with_embedded_images()
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
            note = "autosave"
        # Delegate to _save_date for the currently selected date
        self._save_date(self._current_date_iso(), explicit, note)
        try:
            self._save_timer.start()
        except Exception:
            pass

    def _open_history(self):
        date_iso = self._current_date_iso()
        dlg = HistoryDialog(self.db, date_iso, self)
        if dlg.exec() == QDialog.Accepted:
            # refresh editor + calendar (head pointer may have changed)
            self._load_selected_date(date_iso)
            self._refresh_calendar_marks()

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
        self.editor.insert_images(paths)  # call into the editor

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
        # Center the window in that screen’s available area
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
                self.db.export_by_extension(filename)

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
            # If you’re currently locked, unlock when user disables the timer:
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
        if event.type() == QEvent.KeyPress and not self._locked:
            self._idle_timer.start()
        return super().eventFilter(obj, event)

    def _enter_lock(self):
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

    # ----------------- Close handlers ----------------- #
    def closeEvent(self, event):
        try:
            # Save window position
            self.settings.setValue("main/geometry", self.saveGeometry())
            self.settings.setValue("main/windowState", self.saveState())
            self.settings.setValue("main/maximized", self.isMaximized())

            # Ensure we save any last pending edits to the db
            self._save_current()
            self.db.close()
        except Exception:
            pass
        super().closeEvent(event)
