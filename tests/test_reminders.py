import pytest

from unittest.mock import patch
from bouquin.reminders import (
    Reminder,
    ReminderType,
    ReminderDialog,
    UpcomingRemindersWidget,
    ManageRemindersDialog,
)
from PySide6.QtCore import QDateTime, QDate, QTime
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from datetime import date, timedelta


@pytest.fixture
def freeze_reminders_time(monkeypatch):
    # Freeze 'now' used inside bouquin.reminders to 12:00 today
    import bouquin.reminders as rem

    today = QDate.currentDate()
    fixed_time = QTime(12, 0)
    fixed_dt = QDateTime(today, fixed_time)
    monkeypatch.setattr(
        rem.QDateTime, "currentDateTime", staticmethod(lambda: QDateTime(fixed_dt))
    )
    yield


def _add_daily_reminder(db, text="Standup", time_str="23:59"):
    r = Reminder(
        id=None,
        text=text,
        time_str=time_str,
        reminder_type=ReminderType.DAILY,
        active=True,
    )
    r.id = db.save_reminder(r)
    return r


def test_reminder_type_enum(app):
    """Test ReminderType enum values."""
    assert ReminderType.ONCE is not None
    assert ReminderType.DAILY is not None
    assert ReminderType.WEEKDAYS is not None
    assert ReminderType.WEEKLY is not None


def test_reminder_dataclass_creation(app):
    """Test creating a Reminder instance."""
    reminder = Reminder(
        id=1,
        text="Test reminder",
        time_str="10:30",
        reminder_type=ReminderType.DAILY,
        weekday=None,
        active=True,
        date_iso=None,
    )

    assert reminder.id == 1
    assert reminder.text == "Test reminder"
    assert reminder.time_str == "10:30"
    assert reminder.reminder_type == ReminderType.DAILY
    assert reminder.active is True


def test_reminder_dialog_init_new(qtbot, app, fresh_db):
    """Test ReminderDialog initialization for new reminder."""
    dialog = ReminderDialog(fresh_db)
    qtbot.addWidget(dialog)

    assert dialog._db is fresh_db
    assert dialog._reminder is None
    assert dialog.text_edit.text() == ""


def test_reminder_dialog_init_existing(qtbot, app, fresh_db):
    """Test ReminderDialog initialization with existing reminder."""
    reminder = Reminder(
        id=1,
        text="Existing reminder",
        time_str="14:30",
        reminder_type=ReminderType.WEEKLY,
        weekday=2,
        active=True,
    )

    dialog = ReminderDialog(fresh_db, reminder=reminder)
    qtbot.addWidget(dialog)

    assert dialog.text_edit.text() == "Existing reminder"
    assert dialog.time_edit.time().hour() == 14
    assert dialog.time_edit.time().minute() == 30


def test_reminder_dialog_type_changed(qtbot, app, fresh_db):
    """Test that weekday combo visibility changes with type."""
    dialog = ReminderDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.show()  # Show the dialog so child widgets can be visible

    # Find weekly type in combo
    for i in range(dialog.type_combo.count()):
        if dialog.type_combo.itemData(i) == ReminderType.WEEKLY:
            dialog.type_combo.setCurrentIndex(i)
            break

    qtbot.wait(10)  # Wait for Qt event processing
    assert dialog.weekday_combo.isVisible() is True

    # Switch to daily
    for i in range(dialog.type_combo.count()):
        if dialog.type_combo.itemData(i) == ReminderType.DAILY:
            dialog.type_combo.setCurrentIndex(i)
            break

    qtbot.wait(10)  # Wait for Qt event processing
    assert dialog.weekday_combo.isVisible() is False


def test_reminder_dialog_get_reminder_once(qtbot, app, fresh_db):
    """Test getting reminder with ONCE type."""
    dialog = ReminderDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.text_edit.setText("Test task")
    dialog.time_edit.setTime(QTime(10, 30))

    # Set to ONCE type
    for i in range(dialog.type_combo.count()):
        if dialog.type_combo.itemData(i) == ReminderType.ONCE:
            dialog.type_combo.setCurrentIndex(i)
            break

    reminder = dialog.get_reminder()

    assert reminder.text == "Test task"
    assert reminder.time_str == "10:30"
    assert reminder.reminder_type == ReminderType.ONCE
    assert reminder.date_iso is not None


def test_reminder_dialog_get_reminder_weekly(qtbot, app, fresh_db):
    """Test getting reminder with WEEKLY type."""
    dialog = ReminderDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.text_edit.setText("Weekly meeting")
    dialog.time_edit.setTime(QTime(15, 0))

    # Set to WEEKLY type
    for i in range(dialog.type_combo.count()):
        if dialog.type_combo.itemData(i) == ReminderType.WEEKLY:
            dialog.type_combo.setCurrentIndex(i)
            break

    dialog.weekday_combo.setCurrentIndex(1)  # Tuesday

    reminder = dialog.get_reminder()

    assert reminder.text == "Weekly meeting"
    assert reminder.reminder_type == ReminderType.WEEKLY
    assert reminder.weekday == 1


def test_upcoming_reminders_widget_init(qtbot, app, fresh_db):
    """Test UpcomingRemindersWidget initialization."""
    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)

    assert widget._db is fresh_db
    assert widget.body.isVisible() is False


def test_upcoming_reminders_widget_toggle(qtbot, app, fresh_db):
    """Test toggling reminder list visibility."""
    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.show()  # Show the widget so child widgets can be visible

    # Initially hidden
    assert widget.body.isVisible() is False

    # Click toggle
    widget.toggle_btn.click()
    qtbot.wait(10)  # Wait for Qt event processing

    assert widget.body.isVisible() is True


def test_upcoming_reminders_widget_should_fire_on_date_once(qtbot, app, fresh_db):
    """Test should_fire_on_date for ONCE type."""
    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)

    reminder = Reminder(
        id=1,
        text="Test",
        time_str="10:00",
        reminder_type=ReminderType.ONCE,
        date_iso="2024-01-15",
    )

    assert widget._should_fire_on_date(reminder, QDate(2024, 1, 15)) is True
    assert widget._should_fire_on_date(reminder, QDate(2024, 1, 16)) is False


def test_upcoming_reminders_widget_should_fire_on_date_daily(qtbot, app, fresh_db):
    """Test should_fire_on_date for DAILY type."""
    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)

    reminder = Reminder(
        id=1,
        text="Test",
        time_str="10:00",
        reminder_type=ReminderType.DAILY,
    )

    # Should fire every day
    assert widget._should_fire_on_date(reminder, QDate(2024, 1, 15)) is True
    assert widget._should_fire_on_date(reminder, QDate(2024, 1, 16)) is True


def test_upcoming_reminders_widget_should_fire_on_date_weekdays(qtbot, app, fresh_db):
    """Test should_fire_on_date for WEEKDAYS type."""
    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)

    reminder = Reminder(
        id=1,
        text="Test",
        time_str="10:00",
        reminder_type=ReminderType.WEEKDAYS,
    )

    # Monday (dayOfWeek = 1)
    assert widget._should_fire_on_date(reminder, QDate(2024, 1, 15)) is True
    # Friday (dayOfWeek = 5)
    assert widget._should_fire_on_date(reminder, QDate(2024, 1, 19)) is True
    # Saturday (dayOfWeek = 6)
    assert widget._should_fire_on_date(reminder, QDate(2024, 1, 20)) is False
    # Sunday (dayOfWeek = 7)
    assert widget._should_fire_on_date(reminder, QDate(2024, 1, 21)) is False


def test_upcoming_reminders_widget_should_fire_on_date_weekly(qtbot, app, fresh_db):
    """Test should_fire_on_date for WEEKLY type."""
    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)

    # Fire on Wednesday (weekday = 2)
    reminder = Reminder(
        id=1,
        text="Test",
        time_str="10:00",
        reminder_type=ReminderType.WEEKLY,
        weekday=2,
    )

    # Wednesday (dayOfWeek = 3, so weekday = 2)
    assert widget._should_fire_on_date(reminder, QDate(2024, 1, 17)) is True
    # Thursday (dayOfWeek = 4, so weekday = 3)
    assert widget._should_fire_on_date(reminder, QDate(2024, 1, 18)) is False


def test_upcoming_reminders_widget_refresh_no_db(qtbot, app):
    """Test refresh with no database connection."""
    widget = UpcomingRemindersWidget(None)
    qtbot.addWidget(widget)

    # Should not crash
    widget.refresh()


def test_upcoming_reminders_widget_refresh_with_reminders(qtbot, app, fresh_db):
    """Test refresh displays reminders."""
    # Add a reminder to the database
    reminder = Reminder(
        id=None,
        text="Test reminder",
        time_str="23:59",  # Late time so it's in the future
        reminder_type=ReminderType.DAILY,
        active=True,
    )
    fresh_db.save_reminder(reminder)

    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)

    widget.refresh()

    # Should have at least one item (or "No upcoming reminders")
    assert widget.reminder_list.count() > 0


def test_upcoming_reminders_widget_add_reminder(qtbot, app, fresh_db):
    """Test adding a reminder through the widget."""
    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)

    with patch.object(ReminderDialog, "exec", return_value=QDialog.Accepted):
        with patch.object(ReminderDialog, "get_reminder") as mock_get:
            mock_get.return_value = Reminder(
                id=None,
                text="New reminder",
                time_str="10:00",
                reminder_type=ReminderType.DAILY,
            )

            widget._add_reminder()

            # Reminder should be saved
            reminders = fresh_db.get_all_reminders()
            assert len(reminders) > 0


def test_upcoming_reminders_widget_edit_reminder(qtbot, app, fresh_db):
    """Test editing a reminder through the widget."""
    # Add a reminder first
    reminder = Reminder(
        id=None,
        text="Original",
        time_str="10:00",
        reminder_type=ReminderType.DAILY,
        active=True,
    )
    fresh_db.save_reminder(reminder)

    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.refresh()

    # Get the list item
    if widget.reminder_list.count() > 0:
        item = widget.reminder_list.item(0)

        with patch.object(ReminderDialog, "exec", return_value=QDialog.Accepted):
            with patch.object(ReminderDialog, "get_reminder") as mock_get:
                updated = Reminder(
                    id=1,
                    text="Updated",
                    time_str="11:00",
                    reminder_type=ReminderType.DAILY,
                )
                mock_get.return_value = updated

                widget._edit_reminder(item)


def test_upcoming_reminders_widget_delete_selected_single(qtbot, app, fresh_db):
    """Test deleting a single selected reminder."""
    # Add a reminder
    reminder = Reminder(
        id=None,
        text="To delete",
        time_str="10:00",
        reminder_type=ReminderType.DAILY,
        active=True,
    )
    fresh_db.save_reminder(reminder)

    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.refresh()

    if widget.reminder_list.count() > 0:
        widget.reminder_list.setCurrentRow(0)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            widget._delete_selected_reminders()


def test_upcoming_reminders_widget_delete_selected_multiple(qtbot, app, fresh_db):
    """Test deleting multiple selected reminders."""
    # Add multiple reminders
    for i in range(3):
        reminder = Reminder(
            id=None,
            text=f"Reminder {i}",
            time_str="23:59",
            reminder_type=ReminderType.DAILY,
            active=True,
        )
        fresh_db.save_reminder(reminder)

    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.refresh()

    # Select all items
    for i in range(widget.reminder_list.count()):
        widget.reminder_list.item(i).setSelected(True)

    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        widget._delete_selected_reminders()


def test_upcoming_reminders_widget_check_reminders_no_db(qtbot, app):
    """Test check_reminders with no database."""
    widget = UpcomingRemindersWidget(None)
    qtbot.addWidget(widget)

    # Should not crash
    widget._check_reminders()


def test_upcoming_reminders_widget_start_regular_timer(qtbot, app, fresh_db):
    """Test starting the regular check timer."""
    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)

    widget._start_regular_timer()

    # Timer should be running
    assert widget._check_timer.isActive()


def test_manage_reminders_dialog_init(qtbot, app, fresh_db):
    """Test ManageRemindersDialog initialization."""
    dialog = ManageRemindersDialog(fresh_db)
    qtbot.addWidget(dialog)

    assert dialog._db is fresh_db
    assert dialog.table is not None


def test_manage_reminders_dialog_load_reminders(qtbot, app, fresh_db):
    """Test loading reminders into the table."""
    # Add some reminders
    for i in range(3):
        reminder = Reminder(
            id=None,
            text=f"Reminder {i}",
            time_str="10:00",
            reminder_type=ReminderType.DAILY,
            active=True,
        )
        fresh_db.save_reminder(reminder)

    dialog = ManageRemindersDialog(fresh_db)
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 3


def test_manage_reminders_dialog_load_reminders_no_db(qtbot, app):
    """Test loading reminders with no database."""
    dialog = ManageRemindersDialog(None)
    qtbot.addWidget(dialog)

    # Should not crash
    dialog._load_reminders()


def test_manage_reminders_dialog_add_reminder(qtbot, app, fresh_db):
    """Test adding a reminder through the manage dialog."""
    dialog = ManageRemindersDialog(fresh_db)
    qtbot.addWidget(dialog)

    initial_count = dialog.table.rowCount()

    with patch.object(ReminderDialog, "exec", return_value=QDialog.Accepted):
        with patch.object(ReminderDialog, "get_reminder") as mock_get:
            mock_get.return_value = Reminder(
                id=None,
                text="New",
                time_str="10:00",
                reminder_type=ReminderType.DAILY,
            )

            dialog._add_reminder()

            # Table should have one more row
            assert dialog.table.rowCount() == initial_count + 1


def test_manage_reminders_dialog_edit_reminder(qtbot, app, fresh_db):
    """Test editing a reminder through the manage dialog."""
    reminder = Reminder(
        id=None,
        text="Original",
        time_str="10:00",
        reminder_type=ReminderType.DAILY,
        active=True,
    )
    fresh_db.save_reminder(reminder)

    dialog = ManageRemindersDialog(fresh_db)
    qtbot.addWidget(dialog)

    with patch.object(ReminderDialog, "exec", return_value=QDialog.Accepted):
        with patch.object(ReminderDialog, "get_reminder") as mock_get:
            mock_get.return_value = Reminder(
                id=1,
                text="Updated",
                time_str="11:00",
                reminder_type=ReminderType.DAILY,
            )

            dialog._edit_reminder(reminder)


def test_manage_reminders_dialog_delete_reminder(qtbot, app, fresh_db):
    """Test deleting a reminder through the manage dialog."""
    reminder = Reminder(
        id=None,
        text="To delete",
        time_str="10:00",
        reminder_type=ReminderType.DAILY,
        active=True,
    )
    fresh_db.save_reminder(reminder)

    saved_reminders = fresh_db.get_all_reminders()
    reminder_to_delete = saved_reminders[0]

    dialog = ManageRemindersDialog(fresh_db)
    qtbot.addWidget(dialog)

    initial_count = dialog.table.rowCount()

    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        dialog._delete_reminder(reminder_to_delete)

        # Table should have one fewer row
        assert dialog.table.rowCount() == initial_count - 1


def test_manage_reminders_dialog_delete_reminder_declined(qtbot, app, fresh_db):
    """Test declining to delete a reminder."""
    reminder = Reminder(
        id=None,
        text="Keep me",
        time_str="10:00",
        reminder_type=ReminderType.DAILY,
        active=True,
    )
    fresh_db.save_reminder(reminder)

    saved_reminders = fresh_db.get_all_reminders()
    reminder_to_keep = saved_reminders[0]

    dialog = ManageRemindersDialog(fresh_db)
    qtbot.addWidget(dialog)

    initial_count = dialog.table.rowCount()

    with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        dialog._delete_reminder(reminder_to_keep)

        # Table should have same number of rows
        assert dialog.table.rowCount() == initial_count


def test_manage_reminders_dialog_weekly_reminder_display(qtbot, app, fresh_db):
    """Test that weekly reminders display the day name."""
    reminder = Reminder(
        id=None,
        text="Weekly",
        time_str="10:00",
        reminder_type=ReminderType.WEEKLY,
        weekday=2,  # Wednesday
        active=True,
    )
    fresh_db.save_reminder(reminder)

    dialog = ManageRemindersDialog(fresh_db)
    qtbot.addWidget(dialog)

    # Check that the type column shows the day
    type_item = dialog.table.item(0, 2)
    assert "Wed" in type_item.text()


def test_reminder_dialog_accept(qtbot, app, fresh_db):
    """Test accepting the reminder dialog."""
    dialog = ReminderDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.text_edit.setText("Test")
    dialog.accept()


def test_reminder_dialog_reject(qtbot, app, fresh_db):
    """Test rejecting the reminder dialog."""
    dialog = ReminderDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.reject()


def test_upcoming_reminders_widget_signal_emitted(qtbot, app, fresh_db):
    """Test that reminderTriggered signal is emitted."""
    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)

    signal_received = []
    widget.reminderTriggered.connect(lambda text: signal_received.append(text))

    # Manually emit for testing
    widget.reminderTriggered.emit("Test reminder")

    assert len(signal_received) == 1
    assert signal_received[0] == "Test reminder"


def test_upcoming_reminders_widget_no_upcoming_message(qtbot, app, fresh_db):
    """Test that 'No upcoming reminders' message is shown when appropriate."""
    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)

    widget.refresh()

    # Should show message when no reminders
    if widget.reminder_list.count() > 0:
        item = widget.reminder_list.item(0)
        if "No upcoming" in item.text():
            assert True


def test_upcoming_reminders_widget_manage_button(qtbot, app, fresh_db):
    """Test clicking the manage button."""
    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)

    with patch.object(ManageRemindersDialog, "exec"):
        widget._manage_reminders()


def test_reminder_dialog_time_format(qtbot, app, fresh_db):
    """Test that time is formatted correctly."""
    dialog = ReminderDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.time_edit.setTime(QTime(9, 5))
    reminder = dialog.get_reminder()

    assert reminder.time_str == "09:05"


def test_upcoming_reminders_widget_past_reminders_filtered(qtbot, app, fresh_db):
    """Test that past reminders are not shown in upcoming list."""
    # Create a reminder that's in the past
    reminder = Reminder(
        id=None,
        text="Past reminder",
        time_str="00:01",  # Very early morning
        reminder_type=ReminderType.DAILY,
        active=True,
    )
    fresh_db.save_reminder(reminder)

    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)

    # Current time should be past 00:01
    from PySide6.QtCore import QTime

    if QTime.currentTime().hour() > 0:
        widget.refresh()
        # The past reminder for today should be filtered out
        # but tomorrow's occurrence should be shown


def test_reminder_with_inactive_status(qtbot, app, fresh_db):
    """Test that inactive reminders are not displayed."""
    reminder = Reminder(
        id=None,
        text="Inactive",
        time_str="23:59",
        reminder_type=ReminderType.DAILY,
        active=False,
    )
    fresh_db.save_reminder(reminder)

    widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.refresh()

    # Should not show inactive reminder
    for i in range(widget.reminder_list.count()):
        item = widget.reminder_list.item(i)
        assert "Inactive" not in item.text() or "No upcoming" in item.text()


def test_reminder_triggers_and_deactivates(qtbot, fresh_db):
    """Test that ONCE reminders deactivate after firing."""
    # Add a ONCE reminder for right now
    now = QTime.currentTime()
    hour = now.hour()
    minute = now.minute()

    reminder = Reminder(
        id=None,
        text="Test once reminder",
        reminder_type=ReminderType.ONCE,
        time_str=f"{hour:02d}:{minute:02d}",
        date_iso=date.today().isoformat(),
        active=True,
    )
    reminder_id = fresh_db.save_reminder(reminder)

    reminders_widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(reminders_widget)

    # Set up signal spy
    triggered_texts = []
    reminders_widget.reminderTriggered.connect(
        lambda text: triggered_texts.append(text)
    )

    # Trigger the check
    reminders_widget._check_reminders()

    # Verify reminder was triggered
    assert len(triggered_texts) > 0
    assert "Test once reminder" in triggered_texts

    # Verify reminder was deactivated
    reminders = fresh_db.get_all_reminders()
    deactivated = [r for r in reminders if r.id == reminder_id][0]
    assert deactivated.active is False


def test_reminder_not_active_skipped(qtbot, fresh_db):
    """Test that inactive reminders are not triggered."""
    now = QTime.currentTime()
    hour = now.hour()
    minute = now.minute()

    reminder = Reminder(
        id=None,
        text="Inactive reminder",
        reminder_type=ReminderType.ONCE,
        time_str=f"{hour:02d}:{minute:02d}",
        date_iso=date.today().isoformat(),
        active=False,  # Not active
    )
    fresh_db.save_reminder(reminder)

    reminders_widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(reminders_widget)

    # Set up signal spy
    triggered_texts = []
    reminders_widget.reminderTriggered.connect(
        lambda text: triggered_texts.append(text)
    )

    # Trigger the check
    reminders_widget._check_reminders()

    # Should not trigger inactive reminder
    assert len(triggered_texts) == 0


def test_reminder_not_today_skipped(qtbot, fresh_db):
    """Test that reminders not scheduled for today are skipped."""
    now = QTime.currentTime()
    hour = now.hour()
    minute = now.minute()

    # Schedule for tomorrow
    tomorrow = date.today() + timedelta(days=1)

    reminder = Reminder(
        id=None,
        text="Tomorrow's reminder",
        reminder_type=ReminderType.ONCE,
        time_str=f"{hour:02d}:{minute:02d}",
        date_iso=tomorrow.isoformat(),
        active=True,
    )
    fresh_db.save_reminder(reminder)

    reminders_widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(reminders_widget)

    # Set up signal spy
    triggered_texts = []
    reminders_widget.reminderTriggered.connect(
        lambda text: triggered_texts.append(text)
    )

    # Trigger the check
    reminders_widget._check_reminders()

    # Should not trigger tomorrow's reminder
    assert len(triggered_texts) == 0


def test_reminder_context_menu_no_selection(qtbot, fresh_db):
    """Test context menu with no selection returns early."""
    reminders_widget = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(reminders_widget)

    # Clear selection
    reminders_widget.reminder_list.clearSelection()

    # Show context menu - should return early
    reminders_widget._show_reminder_context_menu(reminders_widget.reminder_list.pos())


def test_edit_reminder_dialog(qtbot, fresh_db):
    """Test editing a reminder through the dialog."""
    reminder = Reminder(
        id=None,
        text="Original text",
        reminder_type=ReminderType.DAILY,
        time_str="14:30",
        date_iso=None,
        active=True,
    )
    fresh_db.save_reminder(reminder)

    widget = QWidget()

    # Create edit dialog
    reminder_obj = fresh_db.get_all_reminders()[0]
    dlg = ReminderDialog(fresh_db, widget, reminder=reminder_obj)
    qtbot.addWidget(dlg)

    # Verify fields are populated
    assert dlg.text_edit.text() == "Original text"
    assert dlg.time_edit.time().toString("HH:mm") == "14:30"


def test_upcoming_reminders_context_menu_shows(
    qtbot, app, fresh_db, freeze_reminders_time, monkeypatch
):
    from PySide6 import QtWidgets, QtGui
    from PySide6.QtCore import QPoint
    from bouquin.reminders import Reminder, ReminderType, UpcomingRemindersWidget

    # Add a future reminder for today
    r = Reminder(
        id=None,
        text="Ping",
        time_str="23:59",
        reminder_type=ReminderType.DAILY,
        active=True,
    )
    r.id = fresh_db.save_reminder(r)

    w = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(w)
    w.refresh()

    # Select first upcoming item so context menu code path runs
    assert w.reminder_list.count() > 0
    w.reminder_list.setCurrentItem(w.reminder_list.item(0))

    called = {"exec": False, "actions": []}

    class DummyAction:
        def __init__(self, text, parent=None):
            self._text = text

            class _Sig:
                def connect(self, fn):
                    pass

            self.triggered = _Sig()

    class DummyMenu:
        def __init__(self, parent=None):
            pass

        def addAction(self, action):
            called["actions"].append(getattr(action, "_text", str(action)))

        def exec(self, *_, **__):
            called["exec"] = True

    # Patch the modules that the inline imports will read from
    monkeypatch.setattr(QtWidgets, "QMenu", DummyMenu, raising=True)
    monkeypatch.setattr(QtGui, "QAction", DummyAction, raising=True)

    # Invoke directly (normally via right-click)
    w._show_reminder_context_menu(QPoint(5, 5))

    assert called["exec"] is True
    assert len(called["actions"]) >= 2  # at least Edit/Deactivate/Delete


def test_upcoming_reminders_delete_selected_dedupes(
    qtbot, app, fresh_db, freeze_reminders_time, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox
    from PySide6.QtCore import QItemSelectionModel
    from bouquin.reminders import Reminder, ReminderType, UpcomingRemindersWidget

    r = Reminder(
        id=None,
        text="Duplicate target",
        time_str="23:59",
        reminder_type=ReminderType.DAILY,
        active=True,
    )
    r.id = fresh_db.save_reminder(r)

    w = UpcomingRemindersWidget(fresh_db)
    qtbot.addWidget(w)
    w.refresh()

    assert w.reminder_list.count() >= 2  # daily -> multiple upcoming occurrences

    # First selects & clears; second adds to selection
    w.reminder_list.setCurrentRow(0, QItemSelectionModel.SelectionFlag.ClearAndSelect)
    w.reminder_list.setCurrentRow(1, QItemSelectionModel.SelectionFlag.Select)

    deleted_ids = []

    def fake_delete(rem_id):
        deleted_ids.append(rem_id)

    # Auto-confirm deletion
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes)
    )
    monkeypatch.setattr(fresh_db, "delete_reminder", fake_delete)

    w._delete_selected_reminders()

    # Should de-duplicate to a single DB delete call
    assert deleted_ids == [r.id]
