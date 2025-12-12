from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PySide6.QtCore import QDate, QDateTime, Qt, QTime, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import strings
from .db import DBManager
from .settings import load_db_config

import requests


class ReminderType(Enum):
    ONCE = strings._("once")
    DAILY = strings._("daily")
    WEEKDAYS = strings._("weekdays")  # Mon-Fri
    WEEKLY = strings._("weekly")  # specific day of week
    FORTNIGHTLY = strings._("fortnightly")  # every 2 weeks
    MONTHLY_DATE = strings._("monthly_same_date")  # same calendar date
    MONTHLY_NTH_WEEKDAY = strings._("monthly_nth_weekday")  # e.g. 3rd Monday


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

        # Date
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")

        if reminder and reminder.date_iso:
            d = QDate.fromString(reminder.date_iso, "yyyy-MM-dd")
            if d.isValid():
                self.date_edit.setDate(d)
            else:
                self.date_edit.setDate(QDate.currentDate())
        else:
            self.date_edit.setDate(QDate.currentDate())

        self.form.addRow("&" + strings._("date") + ":", self.date_edit)

        # Time
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        if reminder:
            parts = reminder.time_str.split(":")
            self.time_edit.setTime(QTime(int(parts[0]), int(parts[1])))
        else:
            # Default to 5 minutes in the future
            future = QTime.currentTime().addSecs(5 * 60)
            self.time_edit.setTime(future)
        self.form.addRow("&" + strings._("time") + ":", self.time_edit)

        # Recurrence type
        self.type_combo = QComboBox()
        self.type_combo.addItem(strings._("once"), ReminderType.ONCE)
        self.type_combo.addItem(strings._("every_day"), ReminderType.DAILY)
        self.type_combo.addItem(strings._("every_weekday"), ReminderType.WEEKDAYS)
        self.type_combo.addItem(strings._("every_week"), ReminderType.WEEKLY)
        self.type_combo.addItem(strings._("every_fortnight"), ReminderType.FORTNIGHTLY)
        self.type_combo.addItem(strings._("every_month"), ReminderType.MONTHLY_DATE)
        self.type_combo.addItem(
            strings._("every_month_nth_weekday"), ReminderType.MONTHLY_NTH_WEEKDAY
        )

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
            self.weekday_combo.setCurrentIndex(self.date_edit.date().dayOfWeek() - 1)

        self.form.addRow("&" + strings._("day") + ":", self.weekday_combo)
        day_label = self.form.labelForField(self.weekday_combo)
        day_label.setVisible(False)

        self.nth_spin = QSpinBox()
        self.nth_spin.setRange(1, 5)  # up to 5th Monday, etc.
        self.nth_spin.setValue(1)
        # If editing an existing MONTHLY_NTH_WEEKDAY reminder, derive the nth from date_iso
        if (
            reminder
            and reminder.reminder_type == ReminderType.MONTHLY_NTH_WEEKDAY
            and reminder.date_iso
        ):
            anchor = QDate.fromString(reminder.date_iso, "yyyy-MM-dd")
            if anchor.isValid():
                nth_index = (anchor.day() - 1) // 7  # 0-based
                self.nth_spin.setValue(nth_index + 1)

        self.form.addRow("&" + strings._("week_in_month") + ":", self.nth_spin)
        nth_label = self.form.labelForField(self.nth_spin)
        nth_label.setVisible(False)
        self.nth_spin.setVisible(False)

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
        """Show/hide weekday / nth selectors based on reminder type."""
        reminder_type = self.type_combo.currentData()

        show_weekday = reminder_type in (
            ReminderType.WEEKLY,
            ReminderType.MONTHLY_NTH_WEEKDAY,
        )
        self.weekday_combo.setVisible(show_weekday)
        day_label = self.form.labelForField(self.weekday_combo)
        day_label.setVisible(show_weekday)

        show_nth = reminder_type == ReminderType.MONTHLY_NTH_WEEKDAY
        nth_label = self.form.labelForField(self.nth_spin)
        self.nth_spin.setVisible(show_nth)
        nth_label.setVisible(show_nth)

        # For new reminders, when switching to a type that uses a weekday,
        # snap the weekday to match the currently selected date.
        if reminder_type in (
            ReminderType.WEEKLY,
            ReminderType.MONTHLY_NTH_WEEKDAY,
        ) and (self._reminder is None or self._reminder.reminder_type != reminder_type):
            dow = self.date_edit.date().dayOfWeek() - 1  # 0..6 (Mon..Sun)
            if 0 <= dow < self.weekday_combo.count():
                self.weekday_combo.setCurrentIndex(dow)

    def get_reminder(self) -> Reminder:
        """Get the configured reminder."""
        reminder_type = self.type_combo.currentData()
        time_obj = self.time_edit.time()
        time_str = f"{time_obj.hour():02d}:{time_obj.minute():02d}"

        weekday = None
        if reminder_type in (ReminderType.WEEKLY, ReminderType.MONTHLY_NTH_WEEKDAY):
            weekday = self.weekday_combo.currentData()

        date_iso = None
        anchor_date = self.date_edit.date()

        if reminder_type == ReminderType.ONCE:
            # Fire once, on the chosen calendar date at the chosen time
            date_iso = anchor_date.toString("yyyy-MM-dd")

        elif reminder_type == ReminderType.FORTNIGHTLY:
            # Anchor: the chosen calendar date. Every 14 days from this date.
            date_iso = anchor_date.toString("yyyy-MM-dd")

        elif reminder_type == ReminderType.MONTHLY_DATE:
            # Anchor: the chosen calendar date. "Same date each month"
            date_iso = anchor_date.toString("yyyy-MM-dd")

        elif reminder_type == ReminderType.MONTHLY_NTH_WEEKDAY:
            # Anchor: the nth weekday for the chosen month (gives us “3rd Monday” etc.)
            weekday = self.weekday_combo.currentData()
            nth_index = self.nth_spin.value() - 1  # 0-based

            first = QDate(anchor_date.year(), anchor_date.month(), 1)
            target_dow = weekday + 1  # Qt: Monday=1
            offset = (target_dow - first.dayOfWeek() + 7) % 7
            anchor = first.addDays(offset + nth_index * 7)

            # If nth weekday doesn't exist in this month, fall back to the last such weekday
            if anchor.month() != anchor_date.month():
                anchor = anchor.addDays(-7)

            date_iso = anchor.toString("yyyy-MM-dd")

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
        self.toggle_btn.setText(strings._("upcoming_reminders"))
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(False)
        self.toggle_btn.setArrowType(Qt.RightArrow)
        self.toggle_btn.clicked.connect(self._on_toggle)

        self.add_btn = QToolButton()
        self.add_btn.setText("⏰")
        self.add_btn.setToolTip(strings._("add_reminder"))
        self.add_btn.setAutoRaise(True)
        self.add_btn.clicked.connect(self._add_reminder)

        self.manage_btn = QToolButton()
        self.manage_btn.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        )
        self.manage_btn.setToolTip(strings._("manage_reminders"))
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
        #
        # We tick once per second, but only hit the DB when the clock is
        # exactly on a :00 second. That way a reminder for HH:MM fires at
        # HH:MM:00, independent of when it was created.
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)  # 1 second
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

        # Also check once on startup so we don't miss reminders that
        # should have fired a moment ago when the app wasn't running.
        QTimer.singleShot(0, self._check_reminders)

    def _on_tick(self) -> None:
        """Called every second; run reminder check only on exact minute boundaries."""
        now = QDateTime.currentDateTime()
        if now.time().second() == 0:
            # Only do the heavier DB work once per minute, at HH:MM:00,
            # so reminders are aligned to the clock and not to when they
            # were created.
            self._check_reminders(now)

    def __del__(self):
        """Cleanup timers when widget is destroyed."""
        try:
            if hasattr(self, "_tick_timer") and self._tick_timer:
                self._tick_timer.stop()
        except Exception:
            pass  # Ignore any cleanup errors

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
            item = QListWidgetItem(strings._("no_upcoming_reminders"))
            item.setFlags(Qt.NoItemFlags)
            self.reminder_list.addItem(item)

    def _should_fire_on_date(self, reminder: Reminder, date: QDate) -> bool:
        """Check if a reminder should fire on a given date."""
        rtype = reminder.reminder_type

        if rtype == ReminderType.ONCE:
            if reminder.date_iso:
                return date.toString("yyyy-MM-dd") == reminder.date_iso
            return False

        if rtype == ReminderType.DAILY:
            return True

        if rtype == ReminderType.WEEKDAYS:
            # Monday=1, Sunday=7
            return 1 <= date.dayOfWeek() <= 5

        if rtype == ReminderType.WEEKLY:
            # Qt: Monday=1, reminder: Monday=0
            return date.dayOfWeek() - 1 == reminder.weekday

        if rtype == ReminderType.FORTNIGHTLY:
            if not reminder.date_iso:
                return False
            anchor = QDate.fromString(reminder.date_iso, "yyyy-MM-dd")
            if not anchor.isValid() or date < anchor:
                return False
            days = anchor.daysTo(date)
            return days % 14 == 0

        if rtype == ReminderType.MONTHLY_DATE:
            if not reminder.date_iso:
                return False
            anchor = QDate.fromString(reminder.date_iso, "yyyy-MM-dd")
            if not anchor.isValid():
                return False
            anchor_day = anchor.day()
            # Clamp to the last day of this month (for 29/30/31)
            first_of_month = QDate(date.year(), date.month(), 1)
            last_of_month = first_of_month.addMonths(1).addDays(-1)
            target_day = min(anchor_day, last_of_month.day())
            return date.day() == target_day

        if rtype == ReminderType.MONTHLY_NTH_WEEKDAY:
            if not reminder.date_iso or reminder.weekday is None:
                return False

            anchor = QDate.fromString(reminder.date_iso, "yyyy-MM-dd")
            if not anchor.isValid():
                return False

            # Which "nth" weekday is the anchor? (0=1st, 1=2nd, etc.)
            anchor_n = (anchor.day() - 1) // 7
            target_dow = reminder.weekday + 1  # Qt dayOfWeek (1..7)

            # Compute the anchor_n-th target weekday in this month
            first = QDate(date.year(), date.month(), 1)
            offset = (target_dow - first.dayOfWeek() + 7) % 7
            candidate = first.addDays(offset + anchor_n * 7)

            # If that nth weekday doesn't exist this month (e.g. 5th Monday), skip
            if candidate.month() != date.month():
                return False

            return date == candidate

        return False

    def _check_reminders(self, now: QDateTime | None = None):
        """
        Check and trigger due reminders.

        This uses absolute clock time, so a reminder for HH:MM will fire
        when the system clock reaches HH:MM:00, independent of when the
        reminder was created.
        """
        # Guard: Check if database connection is valid
        if not self._db or not hasattr(self._db, "conn") or self._db.conn is None:
            return

        if now is None:
            now = QDateTime.currentDateTime()

        today = now.date()
        reminders = self._db.get_all_reminders()

        # Small grace window (in seconds) so we still fire reminders if
        # the app was just opened or the event loop was briefly busy.
        GRACE_WINDOW_SECS = 120  # 2 minutes

        for reminder in reminders:
            if not reminder.active:
                continue

            if not self._should_fire_on_date(reminder, today):
                continue

            # Parse time: stored as "HH:MM", we treat that as HH:MM:00
            hour, minute = map(int, reminder.time_str.split(":"))
            target = QDateTime(today, QTime(hour, minute, 0))

            # Skip if this reminder is still in the future
            if now < target:
                continue

            # How long ago should this reminder have fired?
            seconds_late = target.secsTo(now)  # target -> now

            if 0 <= seconds_late <= GRACE_WINDOW_SECS:
                # Check if we haven't already fired this occurrence
                if not hasattr(self, "_fired_reminders"):
                    self._fired_reminders = {}

                reminder_key = (reminder.id, target.toString())

                if reminder_key in self._fired_reminders:
                    continue

                # Mark as fired and emit
                self._fired_reminders[reminder_key] = now
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

        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)

        # Only show Edit if single item selected
        if len(selected_items) == 1:
            reminder = selected_items[0].data(Qt.UserRole)
            if reminder:
                edit_action = QAction(strings._("edit"), self)
                edit_action.triggered.connect(
                    lambda: self._edit_reminder(selected_items[0])
                )
                menu.addAction(edit_action)

        # Delete option for any selection
        if len(selected_items) == 1:
            delete_text = strings._("delete")
        else:
            delete_text = (
                strings._("delete")
                + f" {len(selected_items)} "
                + strings._("reminders")
            )

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
            msg = (
                strings._("delete")
                + " "
                + strings._("reminder")
                + f" '{reminder.text}'?"
            )
            if reminder.reminder_type != ReminderType.ONCE:
                msg += (
                    "\n\n"
                    + strings._("this_is_a_reminder_of_type")
                    + f" '{reminder.reminder_type.value}'. "
                    + strings._("deleting_it_will_remove_all_future_occurrences")
                )
        else:
            msg = (
                strings._("delete")
                + f"{len(unique_reminders)} "
                + strings._("reminders")
                + " ?\n\n"
                + strings._("this_will_delete_the_actual_reminders")
            )

        reply = QMessageBox.question(
            self,
            strings._("delete_reminders"),
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
        msg = strings._("delete") + " " + strings._("reminder") + f" '{reminder.text}'?"
        if reminder.reminder_type != ReminderType.ONCE:
            msg += (
                "\n\n"
                + strings._("this_is_a_reminder_of_type")
                + f" '{reminder.reminder_type.value}'. "
                + strings._("deleting_it_will_remove_all_future_occurrences")
            )

        reply = QMessageBox.question(
            self,
            strings._("delete_reminder"),
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

        self.setWindowTitle(strings._("manage_reminders"))
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        # Reminder list table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            [
                strings._("text"),
                strings._("date"),
                strings._("time"),
                strings._("type"),
                strings._("active"),
                strings._("actions"),
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)

        # Buttons
        btn_layout = QHBoxLayout()

        add_btn = QPushButton(strings._("add_reminder"))
        add_btn.clicked.connect(self._add_reminder)
        btn_layout.addWidget(add_btn)

        btn_layout.addStretch()

        close_btn = QPushButton(strings._("close"))
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

            # Date
            date_display = ""
            if reminder.reminder_type == ReminderType.ONCE and reminder.date_iso:
                d = QDate.fromString(reminder.date_iso, "yyyy-MM-dd")
                if d.isValid():
                    date_display = d.toString("yyyy-MM-dd")
                else:
                    date_display = reminder.date_iso

            date_item = QTableWidgetItem(date_display)
            self.table.setItem(row, 1, date_item)

            # Time
            time_item = QTableWidgetItem(reminder.time_str)
            self.table.setItem(row, 2, time_item)

            # Type
            base_type_strs = {
                ReminderType.ONCE: "Once",
                ReminderType.DAILY: "Daily",
                ReminderType.WEEKDAYS: "Weekdays",
                ReminderType.WEEKLY: "Weekly",
                ReminderType.FORTNIGHTLY: "Fortnightly",
                ReminderType.MONTHLY_DATE: "Monthly (date)",
                ReminderType.MONTHLY_NTH_WEEKDAY: "Monthly (nth weekday)",
            }
            type_str = base_type_strs.get(reminder.reminder_type, "Unknown")

            # Short day names we can reuse
            days_short = [
                strings._("monday_short"),
                strings._("tuesday_short"),
                strings._("wednesday_short"),
                strings._("thursday_short"),
                strings._("friday_short"),
                strings._("saturday_short"),
                strings._("sunday_short"),
            ]

            if reminder.reminder_type == ReminderType.MONTHLY_NTH_WEEKDAY:
                # Show something like: Monthly (3rd Mon)
                day_name = ""
                if reminder.weekday is not None and 0 <= reminder.weekday < len(
                    days_short
                ):
                    day_name = days_short[reminder.weekday]

                nth_label = ""
                if reminder.date_iso:
                    anchor = QDate.fromString(reminder.date_iso, "yyyy-MM-dd")
                    if anchor.isValid():
                        nth_index = (anchor.day() - 1) // 7  # 0-based (0..4)
                        ordinals = ["1st", "2nd", "3rd", "4th", "5th"]
                        if 0 <= nth_index < len(ordinals):
                            nth_label = ordinals[nth_index]

                parts = []
                if nth_label:
                    parts.append(nth_label)
                if day_name:
                    parts.append(day_name)

                if parts:
                    type_str = f"Monthly ({' '.join(parts)})"
                # else: fall back to the generic "Monthly (nth weekday)"

            else:
                # For weekly / fortnightly types, still append the day name
                if (
                    reminder.reminder_type
                    in (ReminderType.WEEKLY, ReminderType.FORTNIGHTLY)
                    and reminder.weekday is not None
                    and 0 <= reminder.weekday < len(days_short)
                ):
                    type_str += f" ({days_short[reminder.weekday]})"

            type_item = QTableWidgetItem(type_str)
            self.table.setItem(row, 3, type_item)

            # Active
            active_item = QTableWidgetItem("✓" if reminder.active else "✗")
            self.table.setItem(row, 4, active_item)

            # Actions
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(2, 2, 2, 2)

            edit_btn = QPushButton(strings._("edit"))
            edit_btn.clicked.connect(lambda checked, r=reminder: self._edit_reminder(r))
            actions_layout.addWidget(edit_btn)

            delete_btn = QPushButton(strings._("delete"))
            delete_btn.clicked.connect(
                lambda checked, r=reminder: self._delete_reminder(r)
            )
            actions_layout.addWidget(delete_btn)

            self.table.setCellWidget(row, 5, actions_widget)

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
            strings._("delete_reminder"),
            strings._("delete") + " " + strings._("reminder") + f" '{reminder.text}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self._db.delete_reminder(reminder.id)
            self._load_reminders()


class ReminderWebHook:
    def __init__(self, text):
        self.text = text
        self.cfg = load_db_config()

    def _send(self):
        payload: dict[str, str] = {
            "reminder": self.text,
        }

        url = self.cfg.reminders_webhook_url
        secret = self.cfg.reminders_webhook_secret

        _headers = {}
        if secret:
            _headers["X-Bouquin-Secret"] = secret

        if url:
            try:
                requests.post(
                    url,
                    json=payload,
                    timeout=10,
                    headers=_headers,
                )
            except Exception:
                # We did our best
                pass
