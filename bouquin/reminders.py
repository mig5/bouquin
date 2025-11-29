from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PySide6.QtCore import Qt, QDate, QTime, QDateTime, QTimer, Slot, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QTimeEdit,
    QPushButton,
    QFrame,
    QWidget,
    QToolButton,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QSizePolicy,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QHeaderView,
)

from . import strings
from .db import DBManager


class ReminderType(Enum):
    ONCE = strings._("once")
    DAILY = strings._("daily")
    WEEKDAYS = strings._("weekdays")  # Mon-Fri
    WEEKLY = strings._("weekly")  # specific day of week


@dataclass
class Reminder:
    id: Optional[int]
    text: str
    time_str: str  # HH:MM
    reminder_type: ReminderType
    weekday: Optional[int] = None  # 0=Mon, 6=Sun (for weekly type)
    active: bool = True
    date_iso: Optional[str] = None  # For ONCE type


class ReminderDialog(QDialog):
    """Dialog for creating/editing reminders with recurrence support."""

    def __init__(self, db: DBManager, parent=None, reminder: Optional[Reminder] = None):
        super().__init__(parent)
        self._db = db
        self._reminder = reminder

        self.setWindowTitle(
            strings._("set_reminder") if not reminder else strings._("edit_reminder")
        )
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        self.form = QFormLayout()

        # Reminder text
        self.text_edit = QLineEdit()
        if reminder:
            self.text_edit.setText(reminder.text)
        self.form.addRow("&" + strings._("reminder") + ":", self.text_edit)

        # Time
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        if reminder:
            parts = reminder.time_str.split(":")
            self.time_edit.setTime(QTime(int(parts[0]), int(parts[1])))
        else:
            self.time_edit.setTime(QTime.currentTime())
        self.form.addRow("&" + strings._("time") + ":", self.time_edit)

        # Recurrence type
        self.type_combo = QComboBox()
        self.type_combo.addItem(strings._("once_today"), ReminderType.ONCE)
        self.type_combo.addItem(strings._("every_day"), ReminderType.DAILY)
        self.type_combo.addItem(strings._("every_weekday"), ReminderType.WEEKDAYS)
        self.type_combo.addItem(strings._("every_week"), ReminderType.WEEKLY)

        if reminder:
            for i in range(self.type_combo.count()):
                if self.type_combo.itemData(i) == reminder.reminder_type:
                    self.type_combo.setCurrentIndex(i)
                    break

        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self.form.addRow("&" + strings._("repeat") + ":", self.type_combo)

        # Weekday selector (for weekly reminders)
        self.weekday_combo = QComboBox()
        days = [
            strings._("monday"),
            strings._("tuesday"),
            strings._("wednesday"),
            strings._("thursday"),
            strings._("friday"),
            strings._("saturday"),
            strings._("sunday"),
        ]
        for i, day in enumerate(days):
            self.weekday_combo.addItem(day, i)

        if reminder and reminder.weekday is not None:
            self.weekday_combo.setCurrentIndex(reminder.weekday)
        else:
            self.weekday_combo.setCurrentIndex(QDate.currentDate().dayOfWeek() - 1)

        self.form.addRow("&" + strings._("day") + ":", self.weekday_combo)
        day_label = self.form.labelForField(self.weekday_combo)
        day_label.setVisible(False)

        layout.addLayout(self.form)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("&" + strings._("save"))
        save_btn.clicked.connect(self.accept)
        save_btn.setDefault(True)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("&" + strings._("cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        self._on_type_changed()

    def _on_type_changed(self):
        """Show/hide weekday selector based on reminder type."""
        reminder_type = self.type_combo.currentData()
        self.weekday_combo.setVisible(reminder_type == ReminderType.WEEKLY)
        day_label = self.form.labelForField(self.weekday_combo)
        day_label.setVisible(reminder_type == ReminderType.WEEKLY)

    def get_reminder(self) -> Reminder:
        """Get the configured reminder."""
        reminder_type = self.type_combo.currentData()
        time_obj = self.time_edit.time()
        time_str = f"{time_obj.hour():02d}:{time_obj.minute():02d}"

        weekday = None
        if reminder_type == ReminderType.WEEKLY:
            weekday = self.weekday_combo.currentData()

        date_iso = None
        if reminder_type == ReminderType.ONCE:
            # Right now this just means "today at the chosen time".
            date_iso = QDate.currentDate().toString("yyyy-MM-dd")

        return Reminder(
            id=self._reminder.id if self._reminder else None,
            text=self.text_edit.text(),
            time_str=time_str,
            reminder_type=reminder_type,
            weekday=weekday,
            active=self._reminder.active if self._reminder else True,
            date_iso=date_iso,
        )


class UpcomingRemindersWidget(QFrame):
    """Collapsible widget showing upcoming reminders for today and next 7 days."""

    reminderTriggered = Signal(str)  # Emits reminder text

    def __init__(self, db: DBManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._db = db

        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # Header with toggle button
        self.toggle_btn = QToolButton()
        self.toggle_btn.setText("Upcoming Reminders")
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(False)
        self.toggle_btn.setArrowType(Qt.RightArrow)
        self.toggle_btn.clicked.connect(self._on_toggle)

        self.add_btn = QToolButton()
        self.add_btn.setText("⏰")
        self.add_btn.setToolTip("Add Reminder")
        self.add_btn.setAutoRaise(True)
        self.add_btn.clicked.connect(self._add_reminder)

        self.manage_btn = QToolButton()
        self.manage_btn.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        )
        self.manage_btn.setToolTip("Manage All Reminders")
        self.manage_btn.setAutoRaise(True)
        self.manage_btn.clicked.connect(self._manage_reminders)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.toggle_btn)
        header.addStretch()
        header.addWidget(self.add_btn)
        header.addWidget(self.manage_btn)

        # Body with reminder list
        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(2)

        self.reminder_list = QListWidget()
        self.reminder_list.setMaximumHeight(200)
        self.reminder_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.reminder_list.itemDoubleClicked.connect(self._edit_reminder)
        self.reminder_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.reminder_list.customContextMenuRequested.connect(
            self._show_reminder_context_menu
        )
        body_layout.addWidget(self.reminder_list)

        self.body.setVisible(False)

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.addLayout(header)
        main.addWidget(self.body)

        # Timer to check and fire reminders
        # Start by syncing to the next minute boundary
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._check_reminders)

        # Calculate milliseconds until next minute (HH:MM:00)
        now = QDateTime.currentDateTime()
        current_second = now.time().second()
        current_msec = now.time().msec()

        # Milliseconds until next minute
        ms_until_next_minute = (60 - current_second) * 1000 - current_msec

        # Start with a single-shot to sync to the minute
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._start_regular_timer)
        self._sync_timer.start(ms_until_next_minute)

        # Also check immediately in case there are pending reminders
        QTimer.singleShot(1000, self._check_reminders)

    def __del__(self):
        """Cleanup timers when widget is destroyed."""
        try:
            if hasattr(self, "_check_timer") and self._check_timer:
                self._check_timer.stop()
            if hasattr(self, "_sync_timer") and self._sync_timer:
                self._sync_timer.stop()
        except:
            pass  # Ignore any cleanup errors

    def _start_regular_timer(self):
        """Start the regular check timer after initial sync."""
        # Now we're at a minute boundary, check and start regular timer
        self._check_reminders()
        self._check_timer.start(60000)  # Check every minute

    def _on_toggle(self, checked: bool):
        """Toggle visibility of reminder list."""
        self.body.setVisible(checked)
        self.toggle_btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        if checked:
            self.refresh()

    def refresh(self):
        """Reload and display upcoming reminders."""
        # Guard: Check if database connection is valid
        if not self._db or not hasattr(self._db, "conn") or self._db.conn is None:
            return

        self.reminder_list.clear()

        reminders = self._db.get_all_reminders()
        now = QDateTime.currentDateTime()
        today = QDate.currentDate()

        # Get reminders for the next 7 days
        upcoming = []
        for i in range(8):  # Today + 7 days
            check_date = today.addDays(i)

            for reminder in reminders:
                if not reminder.active:
                    continue

                if self._should_fire_on_date(reminder, check_date):
                    # Parse time
                    hour, minute = map(int, reminder.time_str.split(":"))
                    dt = QDateTime(check_date, QTime(hour, minute))

                    # Skip past reminders
                    if dt < now:
                        continue

                    upcoming.append((dt, reminder))

        # Sort by datetime
        upcoming.sort(key=lambda x: x[0])

        # Display
        for dt, reminder in upcoming[:20]:  # Show max 20
            date_str = dt.date().toString("ddd MMM d")
            time_str = dt.time().toString("HH:mm")

            item = QListWidgetItem(f"{date_str} {time_str} - {reminder.text}")
            item.setData(Qt.UserRole, reminder)
            self.reminder_list.addItem(item)

        if not upcoming:
            item = QListWidgetItem("No upcoming reminders")
            item.setFlags(Qt.NoItemFlags)
            self.reminder_list.addItem(item)

    def _should_fire_on_date(self, reminder: Reminder, date: QDate) -> bool:
        """Check if a reminder should fire on a given date."""
        if reminder.reminder_type == ReminderType.ONCE:
            if reminder.date_iso:
                return date.toString("yyyy-MM-dd") == reminder.date_iso
            return False
        elif reminder.reminder_type == ReminderType.DAILY:
            return True
        elif reminder.reminder_type == ReminderType.WEEKDAYS:
            # Monday=1, Sunday=7
            return 1 <= date.dayOfWeek() <= 5
        elif reminder.reminder_type == ReminderType.WEEKLY:
            # Qt: Monday=1, reminder: Monday=0
            return date.dayOfWeek() - 1 == reminder.weekday
        return False

    def _check_reminders(self):
        """Check if any reminders should fire now."""
        # Guard: Check if database connection is valid
        if not self._db or not hasattr(self._db, "conn") or self._db.conn is None:
            return

        now = QDateTime.currentDateTime()
        today = QDate.currentDate()

        # Round current time to the minute (set seconds to 0)
        current_minute = QDateTime(
            today, QTime(now.time().hour(), now.time().minute(), 0)
        )

        reminders = self._db.get_all_reminders()
        for reminder in reminders:
            if not reminder.active:
                continue

            if not self._should_fire_on_date(reminder, today):
                continue

            # Parse time
            hour, minute = map(int, reminder.time_str.split(":"))
            target = QDateTime(today, QTime(hour, minute, 0))

            # Fire if we've passed the target minute (within last 2 minutes to catch missed ones)
            seconds_diff = current_minute.secsTo(target)
            if -120 <= seconds_diff <= 0:
                # Check if we haven't already fired this one
                if not hasattr(self, "_fired_reminders"):
                    self._fired_reminders = {}

                reminder_key = (reminder.id, target.toString())

                # Only fire once per reminder per target time
                if reminder_key not in self._fired_reminders:
                    self._fired_reminders[reminder_key] = current_minute
                    self.reminderTriggered.emit(reminder.text)

                    # For ONCE reminders, deactivate after firing
                    if reminder.reminder_type == ReminderType.ONCE:
                        self._db.update_reminder_active(reminder.id, False)
                        self.refresh()  # Refresh the list to show deactivated reminder

    @Slot()
    def _add_reminder(self):
        """Open dialog to add a new reminder."""
        dlg = ReminderDialog(self._db, self)
        if dlg.exec() == QDialog.Accepted:
            reminder = dlg.get_reminder()
            self._db.save_reminder(reminder)
            self.refresh()

    @Slot(QListWidgetItem)
    def _edit_reminder(self, item: QListWidgetItem):
        """Edit an existing reminder."""
        reminder = item.data(Qt.UserRole)
        if not reminder:
            return

        dlg = ReminderDialog(self._db, self, reminder)
        if dlg.exec() == QDialog.Accepted:
            updated = dlg.get_reminder()
            self._db.save_reminder(updated)
            self.refresh()

    @Slot()
    def _show_reminder_context_menu(self, pos):
        """Show context menu for reminder list item(s)."""
        selected_items = self.reminder_list.selectedItems()
        if not selected_items:
            return

        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction

        menu = QMenu(self)

        # Only show Edit if single item selected
        if len(selected_items) == 1:
            reminder = selected_items[0].data(Qt.UserRole)
            if reminder:
                edit_action = QAction("Edit", self)
                edit_action.triggered.connect(
                    lambda: self._edit_reminder(selected_items[0])
                )
                menu.addAction(edit_action)

        # Delete option for any selection
        if len(selected_items) == 1:
            delete_text = "Delete"
        else:
            delete_text = f"Delete {len(selected_items)} Reminders"

        delete_action = QAction(delete_text, self)
        delete_action.triggered.connect(lambda: self._delete_selected_reminders())
        menu.addAction(delete_action)

        menu.exec(self.reminder_list.mapToGlobal(pos))

    def _delete_selected_reminders(self):
        """Delete all selected reminders (handling duplicates)."""
        selected_items = self.reminder_list.selectedItems()
        if not selected_items:
            return

        # Collect unique reminder IDs
        unique_reminders = {}
        for item in selected_items:
            reminder = item.data(Qt.UserRole)
            if reminder and reminder.id not in unique_reminders:
                unique_reminders[reminder.id] = reminder

        if not unique_reminders:
            return

        # Confirmation message
        if len(unique_reminders) == 1:
            reminder = list(unique_reminders.values())[0]
            msg = f"Delete reminder '{reminder.text}'?"
            if reminder.reminder_type != ReminderType.ONCE:
                msg += f"\n\nNote: This is a {reminder.reminder_type.value} reminder. Deleting it will remove all future occurrences."
        else:
            msg = f"Delete {len(unique_reminders)} reminders?\n\nNote: This will delete the actual reminders, not just individual occurrences."

        reply = QMessageBox.question(
            self,
            "Delete Reminders",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            for reminder_id in unique_reminders:
                self._db.delete_reminder(reminder_id)
            self.refresh()

    def _delete_reminder(self, reminder):
        """Delete a single reminder after confirmation."""
        msg = f"Delete reminder '{reminder.text}'?"
        if reminder.reminder_type != ReminderType.ONCE:
            msg += f"\n\nNote: This is a {reminder.reminder_type.value} reminder. Deleting it will remove all future occurrences."

        reply = QMessageBox.question(
            self,
            "Delete Reminder",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self._db.delete_reminder(reminder.id)
            self.refresh()

    @Slot()
    def _manage_reminders(self):
        """Open dialog to manage all reminders."""
        dlg = ManageRemindersDialog(self._db, self)
        dlg.exec()
        self.refresh()


class ManageRemindersDialog(QDialog):
    """Dialog for managing all reminders."""

    def __init__(self, db: DBManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._db = db

        self.setWindowTitle("Manage Reminders")
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        # Reminder list table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Text", "Time", "Type", "Active", "Actions"]
        )
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)

        # Buttons
        btn_layout = QHBoxLayout()

        add_btn = QPushButton("Add Reminder")
        add_btn.clicked.connect(self._add_reminder)
        btn_layout.addWidget(add_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        self._load_reminders()

    def _load_reminders(self):
        """Load all reminders into the table."""

        # Guard: Check if database connection is valid
        if not self._db or not hasattr(self._db, "conn") or self._db.conn is None:
            return

        reminders = self._db.get_all_reminders()
        self.table.setRowCount(len(reminders))

        for row, reminder in enumerate(reminders):
            # Text
            text_item = QTableWidgetItem(reminder.text)
            text_item.setData(Qt.UserRole, reminder)
            self.table.setItem(row, 0, text_item)

            # Time
            time_item = QTableWidgetItem(reminder.time_str)
            self.table.setItem(row, 1, time_item)

            # Type
            type_str = {
                ReminderType.ONCE: "Once",
                ReminderType.DAILY: "Daily",
                ReminderType.WEEKDAYS: "Weekdays",
                ReminderType.WEEKLY: "Weekly",
            }.get(reminder.reminder_type, "Unknown")

            if (
                reminder.reminder_type == ReminderType.WEEKLY
                and reminder.weekday is not None
            ):
                days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                type_str += f" ({days[reminder.weekday]})"

            type_item = QTableWidgetItem(type_str)
            self.table.setItem(row, 2, type_item)

            # Active
            active_item = QTableWidgetItem("✓" if reminder.active else "✗")
            self.table.setItem(row, 3, active_item)

            # Actions
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(2, 2, 2, 2)

            edit_btn = QPushButton("Edit")
            edit_btn.clicked.connect(lambda checked, r=reminder: self._edit_reminder(r))
            actions_layout.addWidget(edit_btn)

            delete_btn = QPushButton("Delete")
            delete_btn.clicked.connect(
                lambda checked, r=reminder: self._delete_reminder(r)
            )
            actions_layout.addWidget(delete_btn)

            self.table.setCellWidget(row, 4, actions_widget)

    def _add_reminder(self):
        """Add a new reminder."""
        dlg = ReminderDialog(self._db, self)
        if dlg.exec() == QDialog.Accepted:
            reminder = dlg.get_reminder()
            self._db.save_reminder(reminder)
            self._load_reminders()

    def _edit_reminder(self, reminder):
        """Edit an existing reminder."""
        dlg = ReminderDialog(self._db, self, reminder)
        if dlg.exec() == QDialog.Accepted:
            updated = dlg.get_reminder()
            self._db.save_reminder(updated)
            self._load_reminders()

    def _delete_reminder(self, reminder):
        """Delete a reminder."""
        reply = QMessageBox.question(
            self,
            "Delete Reminder",
            f"Delete reminder '{reminder.text}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self._db.delete_reminder(reminder.id)
            self._load_reminders()
