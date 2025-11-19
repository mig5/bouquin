from __future__ import annotations

import csv
import html

from collections import defaultdict
from typing import Optional
from sqlcipher3.dbapi2 import IntegrityError

from PySide6.QtCore import Qt, QDate, QUrl
from PySide6.QtGui import QPainter, QColor, QImage, QTextDocument, QPageLayout
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QFileDialog,
    QFormLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QDoubleSpinBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
    QTabWidget,
    QListWidget,
    QListWidgetItem,
    QDateEdit,
    QMessageBox,
    QCompleter,
    QToolButton,
    QSizePolicy,
    QStyle,
    QInputDialog,
)

from .db import DBManager
from . import strings


class TimeLogWidget(QFrame):
    """
    Collapsible per-page time log summary + button to open the full dialog.
    Shown in the left sidebar above the Tags widget.
    """

    def __init__(self, db: DBManager, parent: QWidget | None = None):
        super().__init__(parent)
        self._db = db
        self._current_date: Optional[str] = None

        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # Header (toggle + open dialog button)
        self.toggle_btn = QToolButton()
        self.toggle_btn.setText(strings._("time_log"))
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(False)
        self.toggle_btn.setArrowType(Qt.RightArrow)
        self.toggle_btn.clicked.connect(self._on_toggle)

        self.open_btn = QToolButton()
        self.open_btn.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        )
        self.open_btn.setToolTip(strings._("open_time_log"))
        self.open_btn.setAutoRaise(True)
        self.open_btn.clicked.connect(self._open_dialog)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.toggle_btn)
        header.addStretch(1)
        header.addWidget(self.open_btn)

        # Body: simple summary label for the day
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 4, 0, 0)
        self.body_layout.setSpacing(4)

        self.summary_label = QLabel(strings._("time_log_no_entries"))
        self.summary_label.setWordWrap(True)
        self.body_layout.addWidget(self.summary_label)
        self.body.setVisible(False)

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.addLayout(header)
        main.addWidget(self.body)

    # ----- external API ------------------------------------------------

    def set_current_date(self, date_iso: str) -> None:
        self._current_date = date_iso
        self._reload_summary()
        if not self.toggle_btn.isChecked():
            self.summary_label.setText(strings._("time_log_collapsed_hint"))

    # ----- internals ---------------------------------------------------

    def _on_toggle(self, checked: bool) -> None:
        self.body.setVisible(checked)
        self.toggle_btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        if checked and self._current_date:
            self._reload_summary()

    def _update_title(self, total_hours: Optional[float]) -> None:
        """Update the header text, optionally including total hours."""
        if total_hours is None:
            self.toggle_btn.setText(strings._("time_log"))
        else:
            self.toggle_btn.setText(
                strings._("time_log_with_total").format(hours=total_hours)
            )

    def _reload_summary(self) -> None:
        if not self._current_date:
            self._update_title(None)
            self.summary_label.setText(strings._("time_log_no_date"))
            return

        rows = self._db.time_log_for_date(self._current_date)
        if not rows:
            self._update_title(None)
            self.summary_label.setText(strings._("time_log_no_entries"))
            return

        total_minutes = sum(r[6] for r in rows)  # index 6 = minutes
        total_hours = total_minutes / 60.0

        # Update header with running total (visible even when collapsed)
        self._update_title(total_hours)

        # Per-project totals
        per_project: dict[str, int] = {}
        for _, _, _, project_name, *_rest in rows:
            minutes = _rest[2]  # activity_id, activity_name, minutes, note
            per_project[project_name] = per_project.get(project_name, 0) + minutes

        lines = [strings._("time_log_total_hours").format(hours=total_hours)]
        for pname, mins in sorted(per_project.items()):
            lines.append(f"- {pname}: {mins/60:.2f}h")

        self.summary_label.setText("\n".join(lines))

    def _open_dialog(self) -> None:
        if not self._current_date:
            return

        dlg = TimeLogDialog(self._db, self._current_date, self)
        dlg.exec()

        # Always refresh summary + header totals
        self._reload_summary()

        if not self.toggle_btn.isChecked():
            self.summary_label.setText(strings._("time_log_collapsed_hint"))


class TimeLogDialog(QDialog):
    """
    Per-day time log dialog.

    Lets you:
      1) choose a project
      2) enter an activity (free-text with autocomplete)
      3) enter time in decimal hours (0.25 = 15 min, 0.17 ≈ 10 min)
      4) manage entries for this date
    """

    def __init__(self, db: DBManager, date_iso: str, parent=None):
        super().__init__(parent)
        self._db = db
        self._date_iso = date_iso
        self._current_entry_id: Optional[int] = None

        self.setWindowTitle(strings._("time_log_for").format(date=date_iso))
        self.resize(900, 600)

        root = QVBoxLayout(self)

        # --- Top: date label
        root.addWidget(QLabel(strings._("time_log_date_label").format(date=date_iso)))

        # --- Project / activity / hours row
        form = QFormLayout()

        # Project
        proj_row = QHBoxLayout()
        self.project_combo = QComboBox()
        self.manage_projects_btn = QPushButton(strings._("manage_projects"))
        self.manage_projects_btn.clicked.connect(self._manage_projects)
        proj_row.addWidget(self.project_combo, 1)
        proj_row.addWidget(self.manage_projects_btn)
        form.addRow(strings._("project"), proj_row)

        # Activity (free text with autocomplete)
        act_row = QHBoxLayout()
        self.activity_edit = QLineEdit()
        self.manage_activities_btn = QPushButton(strings._("manage_activities"))
        self.manage_activities_btn.clicked.connect(self._manage_activities)
        act_row.addWidget(self.activity_edit, 1)
        act_row.addWidget(self.manage_activities_btn)
        form.addRow(strings._("activity"), act_row)

        # Optional Note
        note_row = QHBoxLayout()
        self.note = QLineEdit()
        note_row.addWidget(self.note, 1)
        form.addRow(strings._("note"), note_row)

        # Hours (decimal)
        self.hours_spin = QDoubleSpinBox()
        self.hours_spin.setRange(0.0, 24.0)
        self.hours_spin.setDecimals(2)
        self.hours_spin.setSingleStep(0.25)
        form.addRow(strings._("hours"), self.hours_spin)

        root.addLayout(form)

        # --- Buttons for entry
        btn_row = QHBoxLayout()
        self.add_update_btn = QPushButton(strings._("add_time_entry"))
        self.add_update_btn.clicked.connect(self._on_add_or_update)

        self.delete_btn = QPushButton(strings._("delete_time_entry"))
        self.delete_btn.clicked.connect(self._on_delete_entry)
        self.delete_btn.setEnabled(False)

        self.report_btn = QPushButton(strings._("run_report"))
        self.report_btn.clicked.connect(self._on_run_report)

        btn_row.addStretch(1)
        btn_row.addWidget(self.add_update_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addWidget(self.report_btn)
        root.addLayout(btn_row)

        # --- Table of entries for this date
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            [
                strings._("project"),
                strings._("activity"),
                strings._("note"),
                strings._("hours"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        root.addWidget(self.table, 1)

        # --- Close button
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton(strings._("close"))
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

        # Init data
        self._reload_projects()
        self._reload_activities()
        self._reload_entries()

    # ----- Data loading ------------------------------------------------

    def _reload_projects(self) -> None:
        self.project_combo.clear()
        for proj_id, name in self._db.list_projects():
            self.project_combo.addItem(name, proj_id)

    def _reload_activities(self) -> None:
        activities = [name for _, name in self._db.list_activities()]
        completer = QCompleter(activities, self.activity_edit)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.activity_edit.setCompleter(completer)

    def _reload_entries(self) -> None:
        rows = self._db.time_log_for_date(self._date_iso)
        self.table.setRowCount(len(rows))
        for row_idx, r in enumerate(rows):
            entry_id = r[0]
            project_name = r[3]
            activity_name = r[5]
            note = r[7] or ""
            minutes = r[6]
            hours = minutes / 60.0

            item_proj = QTableWidgetItem(project_name)
            item_act = QTableWidgetItem(activity_name)
            item_note = QTableWidgetItem(note)
            item_hours = QTableWidgetItem(f"{hours:.2f}")

            # store the entry id on the first column
            item_proj.setData(Qt.ItemDataRole.UserRole, entry_id)

            self.table.setItem(row_idx, 0, item_proj)
            self.table.setItem(row_idx, 1, item_act)
            self.table.setItem(row_idx, 2, item_note)
            self.table.setItem(row_idx, 3, item_hours)

        self._current_entry_id = None
        self.delete_btn.setEnabled(False)
        self.add_update_btn.setText(strings._("add_time_entry"))

    # ----- Actions -----------------------------------------------------

    def _ensure_project_id(self) -> Optional[int]:
        """Get selected project_id from combo."""
        idx = self.project_combo.currentIndex()
        if idx < 0:
            return None
        proj_id = self.project_combo.itemData(idx)
        return int(proj_id) if proj_id is not None else None

    def _on_add_or_update(self) -> None:
        proj_id = self._ensure_project_id()
        if proj_id is None:
            QMessageBox.warning(
                self,
                strings._("project_required_title"),
                strings._("project_required_message"),
            )
            return

        activity_name = self.activity_edit.text().strip()
        if not activity_name:
            QMessageBox.warning(
                self,
                strings._("activity_required_title"),
                strings._("activity_required_message"),
            )
            return

        note = self.note.text().strip()
        if not note:
            note = None

        hours = float(self.hours_spin.value())
        minutes = int(round(hours * 60))

        # Create activity if needed
        activity_id = self._db.add_activity(activity_name)

        if self._current_entry_id is None:
            # New entry
            self._db.add_time_log(self._date_iso, proj_id, activity_id, minutes, note)
        else:
            # Update existing
            self._db.update_time_log(
                self._current_entry_id, proj_id, activity_id, minutes, note
            )

        self.note.setText("")
        self._reload_entries()

    def _on_row_selected(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self._current_entry_id = None
            self.delete_btn.setEnabled(False)
            self.add_update_btn.setText(strings._("add_time_entry"))
            return

        row = items[0].row()
        proj_item = self.table.item(row, 0)
        act_item = self.table.item(row, 1)
        note_item = self.table.item(row, 2)
        hours_item = self.table.item(row, 3)
        entry_id = proj_item.data(Qt.ItemDataRole.UserRole)

        self._current_entry_id = int(entry_id)
        self.delete_btn.setEnabled(True)
        self.add_update_btn.setText(strings._("update_time_entry"))

        # push values into the editors
        proj_name = proj_item.text()
        act_name = act_item.text()
        note = note_item.text()
        hours = float(hours_item.text())

        # Set project combo by name
        idx = self.project_combo.findText(proj_name, Qt.MatchFixedString)
        if idx >= 0:
            self.project_combo.setCurrentIndex(idx)

        self.activity_edit.setText(act_name)
        self.note.setText(note)
        self.hours_spin.setValue(hours)

    def _on_delete_entry(self) -> None:
        if self._current_entry_id is None:
            return
        self._db.delete_time_log(self._current_entry_id)
        self._reload_entries()

    def _on_run_report(self) -> None:
        dlg = TimeReportDialog(self._db, self)
        dlg.exec()

    # ----- Project / activity management -------------------------------

    def _manage_projects(self) -> None:
        dlg = TimeCodeManagerDialog(self._db, focus_tab="projects", parent=self)
        dlg.exec()
        self._reload_projects()

    def _manage_activities(self) -> None:
        dlg = TimeCodeManagerDialog(self._db, focus_tab="activities", parent=self)
        dlg.exec()
        self._reload_activities()


class TimeCodeManagerDialog(QDialog):
    """
    Dialog to manage projects and activities, similar spirit to Tag Browser:
    Add / rename / delete without having to log time.
    """

    def __init__(self, db: DBManager, focus_tab: str = "projects", parent=None):
        super().__init__(parent)
        self._db = db

        self.setWindowTitle(strings._("manage_projects_activities"))
        self.resize(500, 400)

        root = QVBoxLayout(self)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # Projects tab
        proj_tab = QWidget()
        proj_layout = QVBoxLayout(proj_tab)
        self.project_list = QListWidget()
        proj_layout.addWidget(self.project_list, 1)

        proj_btn_row = QHBoxLayout()
        self.proj_add_btn = QPushButton(strings._("add_project"))
        self.proj_rename_btn = QPushButton(strings._("rename_project"))
        self.proj_delete_btn = QPushButton(strings._("delete_project"))
        proj_btn_row.addWidget(self.proj_add_btn)
        proj_btn_row.addWidget(self.proj_rename_btn)
        proj_btn_row.addWidget(self.proj_delete_btn)
        proj_layout.addLayout(proj_btn_row)

        self.tabs.addTab(proj_tab, strings._("projects"))

        # Activities tab
        act_tab = QWidget()
        act_layout = QVBoxLayout(act_tab)
        self.activity_list = QListWidget()
        act_layout.addWidget(self.activity_list, 1)

        act_btn_row = QHBoxLayout()
        self.act_add_btn = QPushButton(strings._("add_activity"))
        self.act_rename_btn = QPushButton(strings._("rename_activity"))
        self.act_delete_btn = QPushButton(strings._("delete_activity"))
        act_btn_row.addWidget(self.act_add_btn)
        act_btn_row.addWidget(self.act_rename_btn)
        act_btn_row.addWidget(self.act_delete_btn)
        act_layout.addLayout(act_btn_row)

        self.tabs.addTab(act_tab, strings._("activities"))

        # Close
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton(strings._("close"))
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

        # Wire
        self.proj_add_btn.clicked.connect(self._add_project)
        self.proj_rename_btn.clicked.connect(self._rename_project)
        self.proj_delete_btn.clicked.connect(self._delete_project)

        self.act_add_btn.clicked.connect(self._add_activity)
        self.act_rename_btn.clicked.connect(self._rename_activity)
        self.act_delete_btn.clicked.connect(self._delete_activity)

        # Initial data
        self._reload_projects()
        self._reload_activities()

        if focus_tab == "activities":
            self.tabs.setCurrentIndex(1)

    def _reload_projects(self):
        self.project_list.clear()
        for proj_id, name in self._db.list_projects():
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, proj_id)
            self.project_list.addItem(item)

    def _reload_activities(self):
        self.activity_list.clear()
        for act_id, name in self._db.list_activities():
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, act_id)
            self.activity_list.addItem(item)

    # ---------- helpers ------------------------------------------------

    def _prompt_name(
        self,
        title_key: str,
        label_key: str,
        default: str = "",
    ) -> tuple[str, bool]:
        """Wrapper around QInputDialog.getText with i18n keys."""
        title = strings._(title_key)
        label = strings._(label_key)
        text, ok = QInputDialog.getText(
            self,
            title,
            label,
            QLineEdit.EchoMode.Normal,
            default,
        )
        return text.strip(), ok

    def _selected_project_item(self) -> QListWidgetItem | None:
        items = self.project_list.selectedItems()
        return items[0] if items else None

    def _selected_activity_item(self) -> QListWidgetItem | None:
        items = self.activity_list.selectedItems()
        return items[0] if items else None

    # ---------- projects -----------------------------------------------

    def _add_project(self) -> None:
        name, ok = self._prompt_name(
            "add_project_title",
            "add_project_label",
            "",
        )
        if not ok or not name:
            return

        try:
            self._db.add_project(name)
        except ValueError:
            # Empty / invalid name – nothing to do, but be defensive
            QMessageBox.warning(
                self,
                strings._("invalid_project_title"),
                strings._("invalid_project_message"),
            )
            return

        self._reload_projects()

    def _rename_project(self) -> None:
        item = self._selected_project_item()
        if item is None:
            QMessageBox.information(
                self,
                strings._("select_project_title"),
                strings._("select_project_message"),
            )
            return

        old_name = item.text()
        proj_id = int(item.data(Qt.ItemDataRole.UserRole))

        new_name, ok = self._prompt_name(
            "rename_project_title",
            "rename_project_label",
            old_name,
        )
        if not ok or not new_name or new_name == old_name:
            return

        try:
            self._db.rename_project(proj_id, new_name)
        except IntegrityError as exc:
            QMessageBox.warning(
                self,
                strings._("project_rename_error_title"),
                strings._("project_rename_error_message").format(error=str(exc)),
            )
            return

        self._reload_projects()

    def _delete_project(self) -> None:
        item = self._selected_project_item()
        if item is None:
            QMessageBox.information(
                self,
                strings._("select_project_title"),
                strings._("select_project_message"),
            )
            return

        proj_id = int(item.data(Qt.ItemDataRole.UserRole))
        name = item.text()

        resp = QMessageBox.question(
            self,
            strings._("delete_project_title"),
            strings._("delete_project_confirm").format(name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        try:
            self._db.delete_project(proj_id)
        except IntegrityError:
            # Likely FK constraint: project has time entries
            QMessageBox.warning(
                self,
                strings._("project_delete_error_title"),
                strings._("project_delete_error_message"),
            )
            return

        self._reload_projects()

    # ---------- activities ---------------------------------------------

    def _add_activity(self) -> None:
        name, ok = self._prompt_name(
            "add_activity_title",
            "add_activity_label",
            "",
        )
        if not ok or not name:
            return

        try:
            self._db.add_activity(name)
        except ValueError:
            QMessageBox.warning(
                self,
                strings._("invalid_activity_title"),
                strings._("invalid_activity_message"),
            )
            return

        self._reload_activities()

    def _rename_activity(self) -> None:
        item = self._selected_activity_item()
        if item is None:
            QMessageBox.information(
                self,
                strings._("select_activity_title"),
                strings._("select_activity_message"),
            )
            return

        old_name = item.text()
        act_id = int(item.data(Qt.ItemDataRole.UserRole))

        new_name, ok = self._prompt_name(
            "rename_activity_title",
            "rename_activity_label",
            old_name,
        )
        if not ok or not new_name or new_name == old_name:
            return

        try:
            self._db.rename_activity(act_id, new_name)
        except IntegrityError as exc:
            QMessageBox.warning(
                self,
                strings._("activity_rename_error_title"),
                strings._("activity_rename_error_message").format(error=str(exc)),
            )
            return

        self._reload_activities()

    def _delete_activity(self) -> None:
        item = self._selected_activity_item()
        if item is None:
            QMessageBox.information(
                self,
                strings._("select_activity_title"),
                strings._("select_activity_message"),
            )
            return

        act_id = int(item.data(Qt.ItemDataRole.UserRole))
        name = item.text()

        resp = QMessageBox.question(
            self,
            strings._("delete_activity_title"),
            strings._("delete_activity_confirm").format(name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        try:
            self._db.delete_activity(act_id)
        except IntegrityError:
            # Activity is referenced by time_log
            QMessageBox.warning(
                self,
                strings._("activity_delete_error_title"),
                strings._("activity_delete_error_message"),
            )
            return

        self._reload_activities()


class TimeReportDialog(QDialog):
    """
    Simple report: choose project + date range + granularity (day/week/month).
    Shows decimal hours per time period.
    """

    def __init__(self, db: DBManager, parent=None):
        super().__init__(parent)
        self._db = db

        # state for last run
        self._last_rows: list[tuple[str, str, int]] = []
        self._last_total_minutes: int = 0
        self._last_project_name: str = ""
        self._last_start: str = ""
        self._last_end: str = ""
        self._last_gran_label: str = ""

        self.setWindowTitle(strings._("time_log_report"))
        self.resize(600, 400)

        root = QVBoxLayout(self)

        form = QFormLayout()
        # Project
        self.project_combo = QComboBox()
        for proj_id, name in self._db.list_projects():
            self.project_combo.addItem(name, proj_id)
        form.addRow(strings._("project"), self.project_combo)

        # Date range
        today = QDate.currentDate()
        self.from_date = QDateEdit(today.addDays(-7))
        self.from_date.setCalendarPopup(True)
        self.to_date = QDateEdit(today)
        self.to_date.setCalendarPopup(True)

        range_row = QHBoxLayout()
        range_row.addWidget(self.from_date)
        range_row.addWidget(QLabel("—"))
        range_row.addWidget(self.to_date)
        form.addRow(strings._("date_range"), range_row)

        # Granularity
        self.granularity = QComboBox()
        self.granularity.addItem(strings._("by_day"), "day")
        self.granularity.addItem(strings._("by_week"), "week")
        self.granularity.addItem(strings._("by_month"), "month")
        form.addRow(strings._("group_by"), self.granularity)

        root.addLayout(form)

        # Run and + export buttons
        run_row = QHBoxLayout()
        run_btn = QPushButton(strings._("run_report"))
        run_btn.clicked.connect(self._run_report)

        export_btn = QPushButton(strings._("export_csv"))
        export_btn.clicked.connect(self._export_csv)

        pdf_btn = QPushButton(strings._("export_pdf"))
        pdf_btn.clicked.connect(self._export_pdf)

        run_row.addStretch(1)
        run_row.addWidget(run_btn)
        run_row.addWidget(export_btn)
        run_row.addWidget(pdf_btn)
        root.addLayout(run_row)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            [
                strings._("time_period"),
                strings._("activity"),
                strings._("note"),
                strings._("hours"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        root.addWidget(self.table, 1)

        # Total label
        self.total_label = QLabel("")
        root.addWidget(self.total_label)

        # Close
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton(strings._("close"))
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    def _run_report(self):
        idx = self.project_combo.currentIndex()
        if idx < 0:
            return
        proj_id = int(self.project_combo.itemData(idx))

        start = self.from_date.date().toString("yyyy-MM-dd")
        end = self.to_date.date().toString("yyyy-MM-dd")
        gran = self.granularity.currentData()

        # Keep human-friendly copies for PDF header
        self._last_project_name = self.project_combo.currentText()
        self._last_start = start
        self._last_end = end
        self._last_gran_label = self.granularity.currentText()

        rows = self._db.time_report(proj_id, start, end, gran)

        self._last_rows = rows
        self._last_total_minutes = sum(r[3] for r in rows)

        self.table.setRowCount(len(rows))
        for i, (time_period, activity_name, note, minutes) in enumerate(rows):
            hrs = minutes / 60.0
            self.table.setItem(i, 0, QTableWidgetItem(time_period))
            self.table.setItem(i, 1, QTableWidgetItem(activity_name))
            self.table.setItem(i, 2, QTableWidgetItem(note))
            self.table.setItem(i, 3, QTableWidgetItem(f"{hrs:.2f}"))

        total_hours = self._last_total_minutes / 60.0
        self.total_label.setText(
            strings._("time_report_total").format(hours=total_hours)
        )

    def _export_csv(self):
        if not self._last_rows:
            QMessageBox.information(
                self,
                strings._("no_report_title"),
                strings._("no_report_message"),
            )
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            strings._("export_csv"),
            "",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not filename:
            return

        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)

                # Header
                writer.writerow(
                    [
                        strings._("time_period"),
                        strings._("activity"),
                        strings._("note"),
                        strings._("hours"),
                    ]
                )

                # Data rows
                for time_period, activity_name, note, minutes in self._last_rows:
                    hours = minutes / 60.0
                    writer.writerow([time_period, activity_name, note, f"{hours:.2f}"])

                # Blank line + total
                total_hours = self._last_total_minutes / 60.0
                writer.writerow([])
                writer.writerow([strings._("total"), "", f"{total_hours:.2f}"])
        except OSError as exc:
            QMessageBox.warning(
                self,
                strings._("export_csv_error_title"),
                strings._("export_csv_error_message").format(error=str(exc)),
            )

    def _export_pdf(self):
        if not self._last_rows:
            QMessageBox.information(
                self,
                strings._("no_report_title"),
                strings._("no_report_message"),
            )
            return

        filename, _ = QFileDialog.getSaveFileName(
            self,
            strings._("export_pdf"),
            "",
            "PDF Files (*.pdf);;All Files (*)",
        )
        if not filename:
            return

        # ---------- Build chart image (hours per period) ----------
        per_period_minutes: dict[str, int] = defaultdict(int)
        for period, _activity, note, minutes in self._last_rows:
            per_period_minutes[period] += minutes

        periods = sorted(per_period_minutes.keys())
        chart_w, chart_h = 800, 220
        chart = QImage(chart_w, chart_h, QImage.Format_ARGB32)
        chart.fill(Qt.white)

        if periods:
            painter = QPainter(chart)
            try:
                painter.setRenderHint(QPainter.Antialiasing, True)

                margin = 50
                left = margin + 30  # extra space for Y labels
                top = margin
                right = chart_w - margin
                bottom = chart_h - margin - 20  # room for X labels
                width = right - left
                height = bottom - top

                painter.setPen(Qt.black)

                # Y-axis label "Hours" above the axis
                painter.drawText(
                    left - 50,  # left of the axis
                    top - 30,  # higher up so it doesn't touch the axis line
                    50,
                    20,
                    Qt.AlignRight | Qt.AlignVCenter,
                    strings._("hours"),
                )

                # Border
                painter.drawRect(left, top, width, height)

                max_hours = max(per_period_minutes[p] for p in periods) / 60.0
                if max_hours > 0:
                    n = len(periods)
                    bar_spacing = width / max(1, n)
                    bar_width = bar_spacing * 0.6

                    # Y-axis ticks (0, 1/3, 2/3, max)
                    num_ticks = 3
                    for i in range(num_ticks + 1):
                        val = max_hours * i / num_ticks
                        y_tick = bottom - int((val / max_hours) * height)
                        # small tick mark
                        painter.drawLine(left - 5, y_tick, left, y_tick)
                        # label to the left
                        painter.drawText(
                            left - 40,
                            y_tick - 7,
                            35,
                            14,
                            Qt.AlignRight | Qt.AlignVCenter,
                            f"{val:.1f}",
                        )

                    # Bars
                    painter.setBrush(QColor(80, 140, 200))
                    painter.setPen(Qt.NoPen)

                    for i, period in enumerate(periods):
                        hours = per_period_minutes[period] / 60.0
                        bar_h = int((hours / max_hours) * (height - 10))
                        if bar_h <= 0:
                            continue

                        x_center = left + bar_spacing * (i + 0.5)
                        x = int(x_center - bar_width / 2)
                        y_top_bar = bottom - bar_h

                        painter.drawRect(x, y_top_bar, int(bar_width), bar_h)

                    # X labels after bars, in black
                    painter.setPen(Qt.black)
                    for i, period in enumerate(periods):
                        x_center = left + bar_spacing * (i + 0.5)
                        x = int(x_center - bar_width / 2)
                        painter.drawText(
                            x,
                            bottom + 5,
                            int(bar_width),
                            20,
                            Qt.AlignHCenter | Qt.AlignTop,
                            period,
                        )
            finally:
                painter.end()

        # ---------- Build HTML report ----------
        project = html.escape(self._last_project_name or "")
        start = html.escape(self._last_start or "")
        end = html.escape(self._last_end or "")
        gran = html.escape(self._last_gran_label or "")

        total_hours = self._last_total_minutes / 60.0

        # Table rows (period, activity, hours)
        row_html_parts: list[str] = []
        for period, activity, note, minutes in self._last_rows:
            hours = minutes / 60.0
            row_html_parts.append(
                "<tr>"
                f"<td>{html.escape(period)}</td>"
                f"<td>{html.escape(activity)}</td>"
                f"<td style='text-align:right'>{hours:.2f}</td>"
                "</tr>"
            )
        rows_html = "\n".join(row_html_parts)

        html_doc = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  body {{
    font-family: sans-serif;
    font-size: 10pt;
  }}
  h1 {{
    font-size: 16pt;
    margin-bottom: 4pt;
  }}
  p.meta {{
    margin-top: 0;
    color: #555;
  }}
  img.chart {{
    display: block;
    margin: 12pt 0;
    max-width: 100%;
    height: auto;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin-top: 12pt;
  }}
  th, td {{
    border: 1px solid #ccc;
    padding: 4pt 6pt;
  }}
  th {{
    background-color: #f0f0f0;
  }}
  td.hours {{
    text-align: right;
  }}
</style>
</head>
<body>
  <h1>{html.escape(strings._("time_log_report_title").format(project=project))}</h1>
  <p class="meta">
    {html.escape(strings._("time_log_report_meta").format(
        start=start, end=end, granularity=gran))}
  </p>
  <p><img src="chart" class="chart" /></p>
  <table>
    <tr>
      <th>{html.escape(strings._("time_period"))}</th>
      <th>{html.escape(strings._("activity"))}</th>
      <th>{html.escape(strings._("hours"))}</th>
    </tr>
    {rows_html}
  </table>
  <p><b>{html.escape(strings._("time_report_total").format(hours=total_hours))}</b></p>
</body>
</html>
"""

        # ---------- Render HTML to PDF ----------
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(filename)
        printer.setPageOrientation(QPageLayout.Orientation.Landscape)

        doc = QTextDocument()
        # attach the chart image as a resource
        doc.addResource(QTextDocument.ImageResource, QUrl("chart"), chart)
        doc.setHtml(html_doc)

        try:
            doc.print_(printer)
        except Exception as exc:  # very defensive
            QMessageBox.warning(
                self,
                strings._("export_pdf_error_title"),
                strings._("export_pdf_error_message").format(error=str(exc)),
            )
