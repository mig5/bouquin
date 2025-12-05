import pytest
from datetime import date, timedelta
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QMessageBox,
    QInputDialog,
    QFileDialog,
    QDialog,
)
from sqlcipher3.dbapi2 import IntegrityError

from bouquin.theme import ThemeManager, ThemeConfig, Theme
from bouquin.time_log import (
    TimeLogWidget,
    TimeLogDialog,
    TimeCodeManagerDialog,
    TimeReportDialog,
)
import bouquin.strings as strings

from unittest.mock import patch, MagicMock


@pytest.fixture
def theme_manager(app):
    return ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))


def _today():
    return date.today().isoformat()


def _yesterday():
    return (date.today() - timedelta(days=1)).isoformat()


def _tomorrow():
    return (date.today() + timedelta(days=1)).isoformat()


# ============================================================================
# DB Methods Tests
# ============================================================================


def test_list_projects_empty(fresh_db):
    """List projects on empty db returns empty list."""
    projects = fresh_db.list_projects()
    assert projects == []


def test_add_project(fresh_db):
    """Add a project and verify it's retrievable."""
    proj_id = fresh_db.add_project("Project Alpha")
    assert proj_id > 0

    projects = fresh_db.list_projects()
    assert len(projects) == 1
    assert projects[0] == (proj_id, "Project Alpha")


def test_add_project_duplicate_name(fresh_db):
    """Adding project with duplicate name is idempotent."""
    id1 = fresh_db.add_project("Duplicate")
    id2 = fresh_db.add_project("Duplicate")
    assert id1 == id2

    projects = fresh_db.list_projects()
    assert len(projects) == 1


def test_add_project_empty_name(fresh_db):
    """Adding project with empty name raises ValueError."""
    with pytest.raises(ValueError, match="empty project name"):
        fresh_db.add_project("")

    with pytest.raises(ValueError, match="empty project name"):
        fresh_db.add_project("   ")


def test_add_project_strips_whitespace(fresh_db):
    """Project name is trimmed of leading/trailing whitespace."""
    fresh_db.add_project("  Trimmed  ")
    projects = fresh_db.list_projects()
    assert projects[0][1] == "Trimmed"


def test_list_projects_sorted(fresh_db):
    """Projects are returned sorted case-insensitively by name."""
    fresh_db.add_project("Zebra")
    fresh_db.add_project("alpha")
    fresh_db.add_project("Beta")

    projects = fresh_db.list_projects()
    names = [p[1] for p in projects]
    assert names == ["alpha", "Beta", "Zebra"]


def test_rename_project(fresh_db):
    """Rename a project."""
    proj_id = fresh_db.add_project("Old Name")
    fresh_db.rename_project(proj_id, "New Name")

    projects = fresh_db.list_projects()
    assert len(projects) == 1
    assert projects[0] == (proj_id, "New Name")


def test_rename_project_to_existing_name_raises(fresh_db):
    """Renaming to existing name raises IntegrityError."""
    fresh_db.add_project("Project A")
    id_b = fresh_db.add_project("Project B")

    with pytest.raises(IntegrityError):
        fresh_db.rename_project(id_b, "Project A")


def test_rename_project_empty_name_does_nothing(fresh_db):
    """Renaming to empty string does nothing."""
    proj_id = fresh_db.add_project("Original")
    fresh_db.rename_project(proj_id, "")

    projects = fresh_db.list_projects()
    assert projects[0][1] == "Original"


def test_delete_project(fresh_db):
    """Delete a project."""
    proj_id = fresh_db.add_project("To Delete")
    fresh_db.delete_project(proj_id)

    projects = fresh_db.list_projects()
    assert len(projects) == 0


def test_delete_project_with_time_entries_raises(fresh_db):
    """Deleting project with time entries raises IntegrityError."""
    proj_id = fresh_db.add_project("Active Project")
    act_id = fresh_db.add_activity("Coding")
    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    with pytest.raises(IntegrityError):
        fresh_db.delete_project(proj_id)


def test_list_activities_empty(fresh_db):
    """List activities on empty db returns empty list."""
    activities = fresh_db.list_activities()
    assert activities == []


def test_add_activity(fresh_db):
    """Add an activity and verify it's retrievable."""
    act_id = fresh_db.add_activity("Coding")
    assert act_id > 0

    activities = fresh_db.list_activities()
    assert len(activities) == 1
    assert activities[0] == (act_id, "Coding")


def test_add_activity_duplicate_name(fresh_db):
    """Adding activity with duplicate name is idempotent."""
    id1 = fresh_db.add_activity("Meeting")
    id2 = fresh_db.add_activity("Meeting")
    assert id1 == id2

    activities = fresh_db.list_activities()
    assert len(activities) == 1


def test_add_activity_empty_name(fresh_db):
    """Adding activity with empty name raises ValueError."""
    with pytest.raises(ValueError, match="empty activity name"):
        fresh_db.add_activity("")

    with pytest.raises(ValueError, match="empty activity name"):
        fresh_db.add_activity("   ")


def test_add_activity_strips_whitespace(fresh_db):
    """Activity name is trimmed of leading/trailing whitespace."""
    fresh_db.add_activity("  Planning  ")
    activities = fresh_db.list_activities()
    assert activities[0][1] == "Planning"


def test_list_activities_sorted(fresh_db):
    """Activities are returned sorted case-insensitively by name."""
    fresh_db.add_activity("Writing")
    fresh_db.add_activity("coding")
    fresh_db.add_activity("Planning")

    activities = fresh_db.list_activities()
    names = [a[1] for a in activities]
    assert names == ["coding", "Planning", "Writing"]


def test_rename_activity(fresh_db):
    """Rename an activity."""
    act_id = fresh_db.add_activity("Old Activity")
    fresh_db.rename_activity(act_id, "New Activity")

    activities = fresh_db.list_activities()
    assert len(activities) == 1
    assert activities[0] == (act_id, "New Activity")


def test_rename_activity_to_existing_name_raises(fresh_db):
    """Renaming to existing name raises IntegrityError."""
    fresh_db.add_activity("Activity A")
    id_b = fresh_db.add_activity("Activity B")

    with pytest.raises(IntegrityError):
        fresh_db.rename_activity(id_b, "Activity A")


def test_rename_activity_empty_name_does_nothing(fresh_db):
    """Renaming to empty string does nothing."""
    act_id = fresh_db.add_activity("Original")
    fresh_db.rename_activity(act_id, "")

    activities = fresh_db.list_activities()
    assert activities[0][1] == "Original"


def test_delete_activity(fresh_db):
    """Delete an activity."""
    act_id = fresh_db.add_activity("To Delete")
    fresh_db.delete_activity(act_id)

    activities = fresh_db.list_activities()
    assert len(activities) == 0


def test_delete_activity_with_time_entries_raises(fresh_db):
    """Deleting activity with time entries raises IntegrityError."""
    proj_id = fresh_db.add_project("Some Project")
    act_id = fresh_db.add_activity("Used Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    with pytest.raises(IntegrityError):
        fresh_db.delete_activity(act_id)


def test_add_time_log(fresh_db):
    """Add a time log entry."""
    proj_id = fresh_db.add_project("Research")
    act_id = fresh_db.add_activity("Reading")

    entry_id = fresh_db.add_time_log(_today(), proj_id, act_id, 90, "Paper review")
    assert entry_id > 0

    entries = fresh_db.time_log_for_date(_today())
    assert len(entries) == 1
    entry = entries[0]
    assert entry[0] == entry_id
    assert entry[1] == _today()
    assert entry[2] == proj_id
    assert entry[3] == "Research"
    assert entry[4] == act_id
    assert entry[5] == "Reading"
    assert entry[6] == 90
    assert entry[7] == "Paper review"


def test_add_time_log_creates_page_if_needed(fresh_db):
    """Adding time log creates page row if it doesn't exist."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    # Verify page doesn't exist
    dates = fresh_db.dates_with_content()
    assert _today() not in dates

    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    # Page should now exist (even with no text content)
    entries = fresh_db.time_log_for_date(_today())
    assert len(entries) == 1


def test_add_time_log_without_note(fresh_db):
    """Add time log without note (None)."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    fresh_db.add_time_log(_today(), proj_id, act_id, 30)
    entries = fresh_db.time_log_for_date(_today())
    assert entries[0][7] is None


def test_update_time_log(fresh_db):
    """Update an existing time log entry."""
    proj1_id = fresh_db.add_project("Project 1")
    proj2_id = fresh_db.add_project("Project 2")
    act1_id = fresh_db.add_activity("Activity 1")
    act2_id = fresh_db.add_activity("Activity 2")

    entry_id = fresh_db.add_time_log(_today(), proj1_id, act1_id, 60, "Original")

    fresh_db.update_time_log(entry_id, proj2_id, act2_id, 120, "Updated")

    entries = fresh_db.time_log_for_date(_today())
    assert len(entries) == 1
    entry = entries[0]
    assert entry[0] == entry_id
    assert entry[2] == proj2_id
    assert entry[3] == "Project 2"
    assert entry[4] == act2_id
    assert entry[5] == "Activity 2"
    assert entry[6] == 120
    assert entry[7] == "Updated"


def test_delete_time_log(fresh_db):
    """Delete a time log entry."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    entry_id = fresh_db.add_time_log(_today(), proj_id, act_id, 60)
    fresh_db.delete_time_log(entry_id)

    entries = fresh_db.time_log_for_date(_today())
    assert len(entries) == 0


def test_time_log_for_date_empty(fresh_db):
    """Query time log for date with no entries."""
    entries = fresh_db.time_log_for_date(_today())
    assert entries == []


def test_time_log_for_date_multiple_entries(fresh_db):
    """Query returns multiple entries sorted by project, activity, id."""
    proj_a = fresh_db.add_project("AAA")
    proj_b = fresh_db.add_project("BBB")
    act_x = fresh_db.add_activity("XXX")
    act_y = fresh_db.add_activity("YYY")

    # Add in non-sorted order
    fresh_db.add_time_log(_today(), proj_b, act_y, 10)
    fresh_db.add_time_log(_today(), proj_a, act_x, 20)
    fresh_db.add_time_log(_today(), proj_a, act_y, 30)
    fresh_db.add_time_log(_today(), proj_b, act_x, 40)

    entries = fresh_db.time_log_for_date(_today())
    assert len(entries) == 4

    # Should be sorted by project name, then activity name
    assert entries[0][3] == "AAA" and entries[0][5] == "XXX"
    assert entries[1][3] == "AAA" and entries[1][5] == "YYY"
    assert entries[2][3] == "BBB" and entries[2][5] == "XXX"
    assert entries[3][3] == "BBB" and entries[3][5] == "YYY"


def test_time_report_by_day(fresh_db):
    """Time report grouped by day."""
    proj_id = fresh_db.add_project("Project")
    act1_id = fresh_db.add_activity("Activity 1")
    act2_id = fresh_db.add_activity("Activity 2")

    # Add entries for multiple days
    fresh_db.add_time_log(_yesterday(), proj_id, act1_id, 60)
    fresh_db.add_time_log(_yesterday(), proj_id, act2_id, 30)
    fresh_db.add_time_log(_today(), proj_id, act1_id, 90)
    fresh_db.add_time_log(_today(), proj_id, act2_id, 45)

    report = fresh_db.time_report(proj_id, _yesterday(), _today(), "day")

    assert len(report) == 4
    # Each row is (period, activity_name, total_minutes)
    yesterday_act1 = next(
        r for r in report if r[0] == _yesterday() and r[1] == "Activity 1"
    )
    assert yesterday_act1[3] == 60

    today_act1 = next(r for r in report if r[0] == _today() and r[1] == "Activity 1")
    assert today_act1[3] == 90


def test_time_report_by_week(fresh_db):
    """Time report grouped by week."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    # Add entries spanning multiple weeks
    date1 = "2024-01-01"  # Monday, Week 1
    date2 = "2024-01-03"  # Same week
    date3 = "2024-01-08"  # Following Monday, Week 2

    fresh_db.add_time_log(date1, proj_id, act_id, 60)
    fresh_db.add_time_log(date2, proj_id, act_id, 30)
    fresh_db.add_time_log(date3, proj_id, act_id, 45)

    report = fresh_db.time_report(proj_id, date1, date3, "week")

    # Should have 2 rows (2 weeks)
    assert len(report) == 2

    # First week total
    assert report[0][3] == 90  # 60 + 30
    # Second week total
    assert report[1][3] == 45


def test_time_report_by_month(fresh_db):
    """Time report grouped by month."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    # Add entries spanning multiple months
    date1 = "2024-01-15"
    date2 = "2024-01-25"
    date3 = "2024-02-10"

    fresh_db.add_time_log(date1, proj_id, act_id, 60)
    fresh_db.add_time_log(date2, proj_id, act_id, 30)
    fresh_db.add_time_log(date3, proj_id, act_id, 45)

    report = fresh_db.time_report(proj_id, date1, date3, "month")

    # Should have 2 rows (2 months)
    assert len(report) == 2

    # January total
    jan_row = next(r for r in report if r[0] == "2024-01")
    assert jan_row[3] == 90  # 60 + 30

    # February total
    feb_row = next(r for r in report if r[0] == "2024-02")
    assert feb_row[3] == 45


def test_time_report_multiple_activities(fresh_db):
    """Time report aggregates by activity within period."""
    proj_id = fresh_db.add_project("Project")
    act1_id = fresh_db.add_activity("Activity 1")
    act2_id = fresh_db.add_activity("Activity 2")

    fresh_db.add_time_log(_today(), proj_id, act1_id, 60)
    fresh_db.add_time_log(_today(), proj_id, act1_id, 30)  # Same activity
    fresh_db.add_time_log(_today(), proj_id, act2_id, 45)

    report = fresh_db.time_report(proj_id, _today(), _today(), "day")

    assert len(report) == 2
    act1_row = next(r for r in report if r[1] == "Activity 1")
    assert act1_row[3] == 90  # 60 + 30 aggregated

    act2_row = next(r for r in report if r[1] == "Activity 2")
    assert act2_row[3] == 45


def test_time_report_filters_by_project(fresh_db):
    """Time report only includes specified project."""
    proj1_id = fresh_db.add_project("Project 1")
    proj2_id = fresh_db.add_project("Project 2")
    act_id = fresh_db.add_activity("Activity")

    fresh_db.add_time_log(_today(), proj1_id, act_id, 60)
    fresh_db.add_time_log(_today(), proj2_id, act_id, 90)

    report = fresh_db.time_report(proj1_id, _today(), _today(), "day")

    assert len(report) == 1
    assert report[0][3] == 60


def test_time_report_empty(fresh_db):
    """Time report with no matching entries."""
    proj_id = fresh_db.add_project("Project")

    report = fresh_db.time_report(proj_id, _today(), _today(), "day")
    assert report == []


# ============================================================================
# TimeLogWidget Tests
# ============================================================================


def test_time_log_widget_toggle(qtbot, fresh_db):
    """Toggle expands/collapses the widget."""
    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.show()

    # Initially collapsed
    assert not widget.body.isVisible()
    assert widget.toggle_btn.arrowType() == Qt.RightArrow

    # Toggle to expand
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)
    assert widget.body.isVisible()
    assert widget.toggle_btn.arrowType() == Qt.DownArrow

    # Toggle to collapse
    widget.toggle_btn.setChecked(False)
    widget._on_toggle(False)
    assert not widget.body.isVisible()
    assert widget.toggle_btn.arrowType() == Qt.RightArrow


def test_time_log_widget_set_current_date_no_entries(qtbot, fresh_db):
    """Set current date with no entries."""
    strings.load_strings("en")
    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)

    widget.set_current_date(_today())
    assert widget._current_date == _today()

    # When collapsed, shows hint
    assert "Time log" in widget.summary_label.text()


def test_time_log_widget_set_current_date_with_entries(qtbot, fresh_db):
    """Set current date with entries shows summary."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 90)  # 1.5 hours

    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)

    # Expand first
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)

    widget.set_current_date(_today())

    # Should show total in title
    assert "1.5" in widget.toggle_btn.text() or "1.50" in widget.toggle_btn.text()

    # Body should show breakdown
    summary = widget.summary_label.text()
    assert "Project" in summary


def test_time_log_widget_open_dialog(qtbot, fresh_db, monkeypatch):
    """Open dialog button opens TimeLogDialog."""
    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.set_current_date(_today())

    dialog_shown = {"shown": False}

    def mock_exec(self):
        dialog_shown["shown"] = True
        return 0

    monkeypatch.setattr(TimeLogDialog, "exec", mock_exec)

    widget.open_btn.click()
    assert dialog_shown["shown"]


def test_time_log_widget_no_date_open_dialog_does_nothing(qtbot, fresh_db, monkeypatch):
    """Open dialog with no date set does nothing."""
    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)

    dialog_shown = {"shown": False}

    def mock_exec(self):
        dialog_shown["shown"] = True
        return 0

    monkeypatch.setattr(TimeLogDialog, "exec", mock_exec)

    widget.open_btn.click()
    assert not dialog_shown["shown"]


def test_time_log_widget_updates_after_dialog_close(qtbot, fresh_db, monkeypatch):
    """Widget refreshes summary after dialog closes."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)
    widget.set_current_date(_today())

    # Add entry via DB (simulating dialog action)
    def mock_exec(self):
        fresh_db.add_time_log(_today(), proj_id, act_id, 120)
        return 0

    monkeypatch.setattr(TimeLogDialog, "exec", mock_exec)

    widget.open_btn.click()

    # Summary should be updated
    assert "2.0" in widget.toggle_btn.text() or "2.00" in widget.toggle_btn.text()


# ============================================================================
# TimeLogDialog Tests
# ============================================================================


def test_time_log_dialog_creation(qtbot, fresh_db):
    """TimeLogDialog can be created."""
    strings.load_strings("en")
    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    assert _today() in dialog.windowTitle()
    assert dialog.project_combo.count() == 0
    assert dialog.table.rowCount() == 0


def test_time_log_dialog_loads_projects(qtbot, fresh_db):
    """Dialog loads existing projects into combo."""
    fresh_db.add_project("Project A")
    fresh_db.add_project("Project B")

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    assert dialog.project_combo.count() == 2


def test_time_log_dialog_loads_activities_for_autocomplete(qtbot, fresh_db):
    """Dialog loads activities for autocomplete."""
    fresh_db.add_activity("Coding")
    fresh_db.add_activity("Testing")

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    completer = dialog.activity_edit.completer()
    assert completer is not None


def test_time_log_dialog_loads_existing_entries(qtbot, fresh_db):
    """Dialog loads existing time log entries."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 90)

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 1
    assert "Project" in dialog.table.item(0, 0).text()
    assert "Activity" in dialog.table.item(0, 1).text()
    assert (
        "1.5" in dialog.table.item(0, 3).text()
        or "1.50" in dialog.table.item(0, 3).text()
    )


def test_time_log_dialog_add_entry_without_project_shows_warning(
    qtbot, fresh_db, monkeypatch
):
    """Add entry without selecting project shows warning."""
    strings.load_strings("en")
    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    dialog.activity_edit.setText("Some Activity")
    dialog.hours_spin.setValue(1.0)

    warning_shown = {"shown": False}

    def mock_warning(*args):
        warning_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    dialog._on_add_or_update()
    assert warning_shown["shown"]


def test_time_log_dialog_add_entry_without_activity_shows_warning(
    qtbot, fresh_db, monkeypatch
):
    """Add entry without activity shows warning."""
    strings.load_strings("en")
    fresh_db.add_project("Project")

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.hours_spin.setValue(1.0)

    warning_shown = {"shown": False}

    def mock_warning(*args):
        warning_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    dialog._on_add_or_update()
    assert warning_shown["shown"]


def test_time_log_dialog_add_entry_success(qtbot, fresh_db):
    """Successfully add a new time entry."""
    fresh_db.add_project("Project")

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.activity_edit.setText("New Activity")
    dialog.hours_spin.setValue(2.5)

    dialog._on_add_or_update()

    assert dialog.table.rowCount() == 1
    assert "New Activity" in dialog.table.item(0, 1).text()
    assert (
        "2.5" in dialog.table.item(0, 3).text()
        or "2.50" in dialog.table.item(0, 3).text()
    )


def test_time_log_dialog_select_row_enables_delete(qtbot, fresh_db):
    """Selecting a row enables delete button and populates fields."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 90)

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    # Initially delete is disabled
    assert not dialog.delete_btn.isEnabled()

    # Select first row
    dialog.table.selectRow(0)

    # Delete should be enabled
    assert dialog.delete_btn.isEnabled()

    # Fields should be populated
    assert dialog.activity_edit.text() == "Activity"
    assert dialog.hours_spin.value() == 1.5


def test_time_log_dialog_update_entry(qtbot, fresh_db):
    """Update an existing entry."""
    proj1_id = fresh_db.add_project("Project 1")
    fresh_db.add_project("Project 2")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj1_id, act_id, 60)

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    # Select and modify
    dialog.table.selectRow(0)
    dialog.project_combo.setCurrentIndex(1)  # Project 2
    dialog.hours_spin.setValue(2.0)

    dialog._on_add_or_update()

    # Should still have 1 row (updated, not added)
    assert dialog.table.rowCount() == 1
    assert "Project 2" in dialog.table.item(0, 0).text()
    assert (
        "2.0" in dialog.table.item(0, 3).text()
        or "2.00" in dialog.table.item(0, 3).text()
    )


def test_time_log_dialog_delete_entry(qtbot, fresh_db):
    """Delete a time log entry."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 1

    dialog.table.selectRow(0)
    dialog._on_delete_entry()

    assert dialog.table.rowCount() == 0


def test_time_log_dialog_manage_projects_opens_dialog(qtbot, fresh_db, monkeypatch):
    """Manage projects button opens TimeCodeManagerDialog."""
    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    manager_shown = {"shown": False}

    def mock_exec(self):
        manager_shown["shown"] = True
        return 0

    monkeypatch.setattr(TimeCodeManagerDialog, "exec", mock_exec)

    dialog.manage_projects_btn.click()
    assert manager_shown["shown"]


def test_time_log_dialog_manage_activities_opens_dialog(qtbot, fresh_db, monkeypatch):
    """Manage activities button opens TimeCodeManagerDialog."""
    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    manager_shown = {"shown": False}

    def mock_exec(self):
        manager_shown["shown"] = True
        return 0

    monkeypatch.setattr(TimeCodeManagerDialog, "exec", mock_exec)

    dialog.manage_activities_btn.click()
    assert manager_shown["shown"]


def test_time_log_dialog_run_report_opens_dialog(qtbot, fresh_db, monkeypatch):
    """Run report button opens TimeReportDialog."""
    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    report_shown = {"shown": False}

    def mock_exec(self):
        report_shown["shown"] = True
        return 0

    monkeypatch.setattr(TimeReportDialog, "exec", mock_exec)

    dialog.report_btn.click()
    assert report_shown["shown"]


# ============================================================================
# TimeCodeManagerDialog Tests
# ============================================================================


def test_time_code_manager_dialog_creation(qtbot, fresh_db):
    """TimeCodeManagerDialog can be created."""
    strings.load_strings("en")
    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    assert dialog.tabs.count() == 2
    assert dialog.tabs.currentIndex() == 0  # Projects tab


def test_time_code_manager_dialog_focus_activities_tab(qtbot, fresh_db):
    """Can focus on activities tab initially."""
    dialog = TimeCodeManagerDialog(fresh_db, focus_tab="activities")
    qtbot.addWidget(dialog)

    assert dialog.tabs.currentIndex() == 1


def test_time_code_manager_dialog_loads_projects(qtbot, fresh_db):
    """Dialog loads existing projects."""
    fresh_db.add_project("Project A")
    fresh_db.add_project("Project B")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    assert dialog.project_list.count() == 2


def test_time_code_manager_dialog_loads_activities(qtbot, fresh_db):
    """Dialog loads existing activities."""
    fresh_db.add_activity("Activity 1")
    fresh_db.add_activity("Activity 2")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    assert dialog.activity_list.count() == 2


def test_time_code_manager_add_project(qtbot, fresh_db, monkeypatch):
    """Add a new project."""
    strings.load_strings("en")
    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    def mock_get_text(parent, title, label, mode, default):
        return "New Project", True

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    dialog._add_project()

    assert dialog.project_list.count() == 1
    assert dialog.project_list.item(0).text() == "New Project"


def test_time_code_manager_add_project_cancelled(qtbot, fresh_db, monkeypatch):
    """Cancel adding project."""
    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    def mock_get_text(parent, title, label, mode, default):
        return "", False

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    dialog._add_project()

    assert dialog.project_list.count() == 0


def test_time_code_manager_add_project_invalid_shows_warning(
    qtbot, fresh_db, monkeypatch
):
    """Adding invalid project shows warning."""
    strings.load_strings("en")
    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    def mock_get_text(parent, title, label, mode, default):
        return "Valid Name", True

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    # Force add_project to raise ValueError
    original_add = fresh_db.add_project

    def bad_add(name):
        raise ValueError("empty project name")

    fresh_db.add_project = bad_add

    warning_shown = {"shown": False}

    def mock_warning(*args):
        warning_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    dialog._add_project()
    assert warning_shown["shown"]

    fresh_db.add_project = original_add


def test_time_code_manager_rename_project(qtbot, fresh_db, monkeypatch):
    """Rename an existing project."""
    strings.load_strings("en")
    fresh_db.add_project("Old Name")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_list.setCurrentRow(0)

    def mock_get_text(parent, title, label, mode, default):
        return "New Name", True

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    dialog._rename_project()

    assert dialog.project_list.item(0).text() == "New Name"


def test_time_code_manager_rename_project_no_selection_shows_info(
    qtbot, fresh_db, monkeypatch
):
    """Rename without selection shows info message."""
    strings.load_strings("en")
    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    info_shown = {"shown": False}

    def mock_info(*args):
        info_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "information", mock_info)

    dialog._rename_project()
    assert info_shown["shown"]


def test_time_code_manager_rename_project_to_duplicate_shows_warning(
    qtbot, fresh_db, monkeypatch
):
    """Renaming to duplicate name shows warning."""
    strings.load_strings("en")
    fresh_db.add_project("Project A")
    fresh_db.add_project("Project B")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_list.setCurrentRow(1)

    def mock_get_text(parent, title, label, mode, default):
        return "Project A", True

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    warning_shown = {"shown": False}

    def mock_warning(*args):
        warning_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    dialog._rename_project()
    assert warning_shown["shown"]


def test_time_code_manager_delete_project(qtbot, fresh_db, monkeypatch):
    """Delete a project."""
    strings.load_strings("en")
    fresh_db.add_project("To Delete")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_list.setCurrentRow(0)

    def mock_question(*args, **kwargs):
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", mock_question)

    dialog._delete_project()

    assert dialog.project_list.count() == 0


def test_time_code_manager_delete_project_cancelled(qtbot, fresh_db, monkeypatch):
    """Cancel delete project."""
    strings.load_strings("en")
    fresh_db.add_project("Keep Me")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_list.setCurrentRow(0)

    def mock_question(*args, **kwargs):
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", mock_question)

    dialog._delete_project()

    assert dialog.project_list.count() == 1


def test_time_code_manager_delete_project_with_entries_shows_warning(
    qtbot, fresh_db, monkeypatch
):
    """Deleting project with entries shows warning."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Used Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_list.setCurrentRow(0)

    def mock_question(*args, **kwargs):
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", mock_question)

    warning_shown = {"shown": False}

    def mock_warning(*args):
        warning_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    dialog._delete_project()
    assert warning_shown["shown"]
    assert dialog.project_list.count() == 1  # Not deleted


def test_time_code_manager_add_activity(qtbot, fresh_db, monkeypatch):
    """Add a new activity."""
    strings.load_strings("en")
    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    def mock_get_text(parent, title, label, mode, default):
        return "New Activity", True

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    dialog._add_activity()

    assert dialog.activity_list.count() == 1
    assert dialog.activity_list.item(0).text() == "New Activity"


def test_time_code_manager_rename_activity(qtbot, fresh_db, monkeypatch):
    """Rename an existing activity."""
    strings.load_strings("en")
    fresh_db.add_activity("Old Activity")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.activity_list.setCurrentRow(0)

    def mock_get_text(parent, title, label, mode, default):
        return "New Activity", True

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    dialog._rename_activity()

    assert dialog.activity_list.item(0).text() == "New Activity"


def test_time_code_manager_delete_activity(qtbot, fresh_db, monkeypatch):
    """Delete an activity."""
    strings.load_strings("en")
    fresh_db.add_activity("To Delete")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.activity_list.setCurrentRow(0)

    def mock_question(*args, **kwargs):
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", mock_question)

    dialog._delete_activity()

    assert dialog.activity_list.count() == 0


def test_time_code_manager_delete_activity_with_entries_shows_warning(
    qtbot, fresh_db, monkeypatch
):
    """Deleting activity with entries shows warning."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Used Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.activity_list.setCurrentRow(0)

    def mock_question(*args, **kwargs):
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", mock_question)

    warning_shown = {"shown": False}

    def mock_warning(*args):
        warning_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    dialog._delete_activity()
    assert warning_shown["shown"]
    assert dialog.activity_list.count() == 1  # Not deleted


# ============================================================================
# TimeReportDialog Tests
# ============================================================================


def test_time_report_dialog_creation(qtbot, fresh_db):
    """TimeReportDialog can be created."""
    strings.load_strings("en")
    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    assert dialog.project_combo.count() == 1
    assert dialog.granularity.count() == 4


def test_time_report_dialog_loads_projects(qtbot, fresh_db):
    """Dialog loads projects."""
    fresh_db.add_project("Project A")
    fresh_db.add_project("Project B")

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    assert dialog.project_combo.count() == 3


def test_time_report_dialog_default_date_range(qtbot, fresh_db):
    """Dialog defaults to start of month."""
    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    today = QDate.currentDate()
    start_of_month = QDate(today.year(), today.month(), 1)

    assert dialog.from_date.date() == start_of_month
    assert dialog.to_date.date() == today


def test_time_report_dialog_run_report(qtbot, fresh_db):
    """Run a time report."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 90)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.from_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    idx_day = dialog.granularity.findData("day")
    assert idx_day != -1
    dialog.granularity.setCurrentIndex(idx_day)

    dialog._run_report()

    assert dialog.table.rowCount() == 1
    assert "Activity" in dialog.table.item(0, 2).text()
    assert "1.5" in dialog.total_label.text() or "1.50" in dialog.total_label.text()


def test_time_report_dialog_run_report_no_project_selected(qtbot, fresh_db):
    """Run report with no project selected does nothing."""
    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog._run_report()

    # Should not crash, table remains empty
    assert dialog.table.rowCount() == 0


def test_time_report_dialog_export_csv_no_report_shows_info(
    qtbot, fresh_db, monkeypatch
):
    """Export CSV without running report shows info."""
    strings.load_strings("en")
    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    info_shown = {"shown": False}

    def mock_info(*args):
        info_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "information", mock_info)

    dialog._export_csv()
    assert info_shown["shown"]


def test_time_report_dialog_export_csv_success(qtbot, fresh_db, tmp_path, monkeypatch):
    """Export report to CSV."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 120)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.from_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))

    dialog._run_report()

    csv_file = str(tmp_path / "report.csv")

    def mock_get_save_filename(*args, **kwargs):
        return csv_file, "CSV Files (*.csv)"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", mock_get_save_filename)

    dialog._export_csv()

    import os

    assert os.path.exists(csv_file)

    with open(csv_file, "r") as f:
        content = f.read()
        assert "Activity" in content
        assert "2.00" in content


def test_time_report_dialog_export_csv_cancelled(qtbot, fresh_db, monkeypatch):
    """Cancel CSV export."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog._run_report()

    def mock_get_save_filename(*args, **kwargs):
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", mock_get_save_filename)

    # Should not crash
    dialog._export_csv()


def test_time_report_dialog_export_pdf_no_report_shows_info(
    qtbot, fresh_db, monkeypatch
):
    """Export PDF without running report shows info."""
    strings.load_strings("en")
    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    info_shown = {"shown": False}

    def mock_info(*args):
        info_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "information", mock_info)

    dialog._export_pdf()
    assert info_shown["shown"]


def test_time_report_dialog_export_pdf_success(qtbot, fresh_db, tmp_path, monkeypatch):
    """Export report to PDF."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Test Project")
    act_id = fresh_db.add_activity("Testing")
    fresh_db.add_time_log(_today(), proj_id, act_id, 150)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.from_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))

    dialog._run_report()

    pdf_file = str(tmp_path / "report.pdf")

    def mock_get_save_filename(*args, **kwargs):
        return pdf_file, "PDF Files (*.pdf)"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", mock_get_save_filename)

    dialog._export_pdf()

    import os

    assert os.path.exists(pdf_file)
    # PDF should have content
    assert os.path.getsize(pdf_file) > 0


def test_time_report_dialog_export_pdf_cancelled(qtbot, fresh_db, monkeypatch):
    """Cancel PDF export."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog._run_report()

    def mock_get_save_filename(*args, **kwargs):
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", mock_get_save_filename)

    # Should not crash
    dialog._export_pdf()


def test_time_report_dialog_granularity_week(qtbot, fresh_db):
    """Report with week granularity."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    # Add entries on different days of the same week
    date1 = "2024-01-01"
    date2 = "2024-01-03"
    fresh_db.add_time_log(date1, proj_id, act_id, 60)
    fresh_db.add_time_log(date2, proj_id, act_id, 90)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.from_date.setDate(QDate.fromString(date1, "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(date2, "yyyy-MM-dd"))

    idx_week = dialog.granularity.findData("week")
    assert idx_week != -1
    dialog.granularity.setCurrentIndex(idx_week)

    dialog._run_report()

    # Should aggregate to single week
    assert dialog.table.rowCount() == 1
    # In grouped modes the Note column is hidden → hours are in column 3
    hours_text = dialog.table.item(0, 3).text()

    assert "2.5" in hours_text or "2.50" in hours_text


def test_time_report_dialog_granularity_month(qtbot, fresh_db):
    """Report with month granularity."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    # Add entries on different days of the same month
    date1 = "2024-01-05"
    date2 = "2024-01-25"
    fresh_db.add_time_log(date1, proj_id, act_id, 60)
    fresh_db.add_time_log(date2, proj_id, act_id, 90)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.from_date.setDate(QDate.fromString(date1, "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(date2, "yyyy-MM-dd"))

    idx_month = dialog.granularity.findData("month")
    assert idx_month != -1
    dialog.granularity.setCurrentIndex(idx_month)

    dialog._run_report()

    # Should aggregate to single month
    assert dialog.table.rowCount() == 1
    hours_text = dialog.table.item(0, 3).text()

    assert "2.5" in hours_text or "2.50" in hours_text


def test_time_report_dialog_multiple_activities_same_period(qtbot, fresh_db):
    """Report shows multiple activities separately."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act1_id = fresh_db.add_activity("Activity 1")
    act2_id = fresh_db.add_activity("Activity 2")

    fresh_db.add_time_log(_today(), proj_id, act1_id, 60)
    fresh_db.add_time_log(_today(), proj_id, act2_id, 90)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.from_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))

    dialog._run_report()

    assert dialog.table.rowCount() == 2


def test_time_log_widget_calculates_per_project_totals(qtbot, fresh_db):
    """Widget shows per-project breakdown in summary."""
    strings.load_strings("en")
    proj1_id = fresh_db.add_project("Project A")
    proj2_id = fresh_db.add_project("Project B")
    act_id = fresh_db.add_activity("Activity")

    fresh_db.add_time_log(_today(), proj1_id, act_id, 60)
    fresh_db.add_time_log(_today(), proj2_id, act_id, 90)

    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)
    widget.set_current_date(_today())

    summary = widget.summary_label.text()
    assert "Project A" in summary
    assert "Project B" in summary
    assert "1.00h" in summary
    assert "1.50h" in summary


# ============================================================================
# Additional TimeLogWidget Edge Cases
# ============================================================================


def test_time_log_widget_collapsed_shows_hint_after_date_set(qtbot, fresh_db):
    """When collapsed, setting date shows hint instead of full summary."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 90)

    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)

    # Keep collapsed
    assert not widget.toggle_btn.isChecked()

    widget.set_current_date(_today())

    # Should show hint, not full breakdown
    assert (
        "hint" in widget.summary_label.text().lower()
        or "time log" in widget.summary_label.text().lower()
    )


def test_time_log_widget_no_date_shows_no_date_message(qtbot, fresh_db):
    """Widget with no date set shows appropriate message."""
    strings.load_strings("en")
    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)

    # Expand to see summary
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)

    # Don't set a date
    widget._reload_summary()

    # Should indicate no date is set
    summary = widget.summary_label.text()
    assert "no date" in summary.lower() or "time log" in summary.lower()


def test_time_log_widget_header_updates_on_toggle(qtbot, fresh_db):
    """Header total is visible even when collapsed."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 120)  # 2 hours

    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.set_current_date(_today())

    # Expand to trigger reload
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)

    # Header should show total
    assert "2" in widget.toggle_btn.text()

    # Collapse again
    widget.toggle_btn.setChecked(False)
    widget._on_toggle(False)

    # Header total should still be visible
    assert "2" in widget.toggle_btn.text()


def test_time_log_widget_dialog_updates_on_close_when_collapsed(
    qtbot, fresh_db, monkeypatch
):
    """When dialog closes, widget updates summary even if collapsed."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.set_current_date(_today())

    # Keep collapsed
    assert not widget.toggle_btn.isChecked()

    def mock_exec(self):
        fresh_db.add_time_log(_today(), proj_id, act_id, 60)
        return 0

    monkeypatch.setattr(TimeLogDialog, "exec", mock_exec)

    widget.open_btn.click()

    # Should show hint after update when collapsed
    assert (
        "hint" in widget.summary_label.text().lower()
        or "time log" in widget.summary_label.text().lower()
    )


# ============================================================================
# Additional TimeLogDialog Edge Cases
# ============================================================================


def test_time_log_dialog_deselect_clears_current_entry(qtbot, fresh_db):
    """Deselecting row clears current entry and disables delete."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    # Select
    dialog.table.selectRow(0)
    assert dialog.delete_btn.isEnabled()

    # Clear selection
    dialog.table.clearSelection()

    # Trigger selection changed
    dialog._on_row_selected()

    assert not dialog.delete_btn.isEnabled()
    assert dialog._current_entry_id is None


def test_time_log_dialog_delete_without_selection_does_nothing(qtbot, fresh_db):
    """Delete button when no entry selected does nothing."""
    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    # No selection
    dialog._current_entry_id = None

    # Should not crash
    dialog._on_delete_entry()


def test_time_log_dialog_creates_activity_if_new(qtbot, fresh_db):
    """Dialog creates activity if it doesn't exist."""
    fresh_db.add_project("Project")

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.activity_edit.setText("Brand New Activity")
    dialog.hours_spin.setValue(1.0)

    dialog._on_add_or_update()

    # Activity should have been created
    activities = fresh_db.list_activities()
    assert len(activities) == 1
    assert activities[0][1] == "Brand New Activity"


def test_time_log_dialog_rounds_hours_to_minutes(qtbot, fresh_db):
    """Hours are correctly converted to integer minutes."""
    fresh_db.add_project("Project")

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.activity_edit.setText("Activity")
    dialog.hours_spin.setValue(1.75)  # 1 hour 45 minutes = 105 minutes

    dialog._on_add_or_update()

    entries = fresh_db.time_log_for_date(_today())
    assert entries[0][6] == 105  # minutes


def test_time_log_dialog_update_button_text_changes(qtbot, fresh_db):
    """Button text changes between Add and Update."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    # Initially "Add"
    assert "add" in dialog.add_update_btn.text().lower()

    # Select entry
    dialog.table.selectRow(0)

    # Should change to "Update"
    assert "update" in dialog.add_update_btn.text().lower()

    # Deselect
    dialog.table.clearSelection()
    dialog._on_row_selected()

    # Back to "Add"
    assert "add" in dialog.add_update_btn.text().lower()


def test_time_log_dialog_project_selection_by_name(qtbot, fresh_db):
    """Selecting entry sets project combo by name match."""
    fresh_db.add_project("Project A")
    proj2_id = fresh_db.add_project("Project B")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj2_id, act_id, 60)

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    dialog.table.selectRow(0)

    # Should select Project B
    assert dialog.project_combo.currentText() == "Project B"


def test_time_log_dialog_project_not_found_in_combo(qtbot, fresh_db):
    """If project name not found in combo, selection doesn't crash."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    entry_id = fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    # Delete the project from DB manually (shouldn't happen, but defensive)
    fresh_db.delete_time_log(entry_id)
    fresh_db.delete_project(proj_id)

    # Re-add entry with orphaned project reference (simulated edge case)
    # Actually can't easily simulate this due to FK constraints
    # So just test normal case - combo should work fine
    proj_id = fresh_db.add_project("Project")
    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    dialog.table.selectRow(0)
    # Should not crash


# ============================================================================
# Additional TimeCodeManagerDialog Edge Cases
# ============================================================================


def test_time_code_manager_rename_cancelled_does_nothing(qtbot, fresh_db, monkeypatch):
    """Cancelling rename does nothing."""
    strings.load_strings("en")
    fresh_db.add_project("Original")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_list.setCurrentRow(0)

    def mock_get_text(parent, title, label, mode, default):
        return "", False

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    dialog._rename_project()

    # Name should remain unchanged
    assert dialog.project_list.item(0).text() == "Original"


def test_time_code_manager_rename_to_same_name_does_nothing(
    qtbot, fresh_db, monkeypatch
):
    """Renaming to same name does nothing."""
    strings.load_strings("en")
    fresh_db.add_project("Same Name")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_list.setCurrentRow(0)

    def mock_get_text(parent, title, label, mode, default):
        return "Same Name", True

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    dialog._rename_project()

    # Should still have one project
    assert dialog.project_list.count() == 1


def test_time_code_manager_delete_no_selection_shows_info(qtbot, fresh_db, monkeypatch):
    """Delete without selection shows info."""
    strings.load_strings("en")
    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    info_shown = {"shown": False}

    def mock_info(*args):
        info_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "information", mock_info)

    dialog._delete_project()
    assert info_shown["shown"]


def test_time_code_manager_add_empty_activity_cancelled(qtbot, fresh_db, monkeypatch):
    """Adding empty activity name is cancelled."""
    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    def mock_get_text(parent, title, label, mode, default):
        return "", True  # Empty but OK clicked

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    dialog._add_activity()

    # No activity should be added
    assert dialog.activity_list.count() == 0


def test_time_code_manager_rename_activity_no_selection(qtbot, fresh_db, monkeypatch):
    """Rename activity without selection shows info."""
    strings.load_strings("en")
    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    info_shown = {"shown": False}

    def mock_info(*args):
        info_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "information", mock_info)

    dialog._rename_activity()
    assert info_shown["shown"]


def test_time_code_manager_delete_activity_no_selection(qtbot, fresh_db, monkeypatch):
    """Delete activity without selection shows info."""
    strings.load_strings("en")
    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    info_shown = {"shown": False}

    def mock_info(*args):
        info_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "information", mock_info)

    dialog._delete_activity()
    assert info_shown["shown"]


def test_time_code_manager_delete_activity_cancelled(qtbot, fresh_db, monkeypatch):
    """Cancelling delete activity keeps it."""
    strings.load_strings("en")
    fresh_db.add_activity("Keep Me")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.activity_list.setCurrentRow(0)

    def mock_question(*args, **kwargs):
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", mock_question)

    dialog._delete_activity()

    assert dialog.activity_list.count() == 1


# ============================================================================
# Additional TimeReportDialog Edge Cases
# ============================================================================


def test_time_report_dialog_empty_report_shows_zero(qtbot, fresh_db):
    """Running report with no data shows zero total."""
    strings.load_strings("en")
    fresh_db.add_project("Project")

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog._run_report()

    assert dialog.table.rowCount() == 0
    assert "0" in dialog.total_label.text()


def test_time_report_dialog_date_range_filters_correctly(qtbot, fresh_db):
    """Report only includes entries within date range."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    # Add entries on different dates
    date1 = "2024-01-01"
    date2 = "2024-01-15"
    date3 = "2024-01-30"

    fresh_db.add_time_log(date1, proj_id, act_id, 60)
    fresh_db.add_time_log(date2, proj_id, act_id, 60)
    fresh_db.add_time_log(date3, proj_id, act_id, 60)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    # Set range to only include middle date
    dialog.from_date.setDate(QDate.fromString(date2, "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(date2, "yyyy-MM-dd"))

    dialog._run_report()

    # Should only have one entry
    assert dialog.table.rowCount() == 1


def test_time_report_dialog_stores_report_state(qtbot, fresh_db):
    """Dialog stores last report state for export."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("My Project")
    act_id = fresh_db.add_activity("My Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 90)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(1)
    dialog.from_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))

    idx_week = dialog.granularity.findData("week")
    assert idx_week != -1
    dialog.granularity.setCurrentIndex(idx_week)

    dialog._run_report()

    # Check stored state
    assert dialog._last_project_name == "My Project"
    assert dialog._last_start == _today()
    assert dialog._last_end == _today()
    assert "week" in dialog._last_gran_label.lower()
    assert len(dialog._last_rows) == 1
    assert dialog._last_total_minutes == 90


def test_time_report_dialog_pdf_export_with_multiple_periods(
    qtbot, fresh_db, tmp_path, monkeypatch
):
    """PDF export handles multiple time periods with chart."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    # Add entries on multiple days
    date1 = "2024-01-01"
    date2 = "2024-01-02"
    date3 = "2024-01-03"

    fresh_db.add_time_log(date1, proj_id, act_id, 60)
    fresh_db.add_time_log(date2, proj_id, act_id, 90)
    fresh_db.add_time_log(date3, proj_id, act_id, 45)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.from_date.setDate(QDate.fromString(date1, "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(date3, "yyyy-MM-dd"))

    idx_day = dialog.granularity.findData("day")
    assert idx_day != -1
    dialog.granularity.setCurrentIndex(idx_day)

    dialog._run_report()

    pdf_file = str(tmp_path / "chart_test.pdf")

    def mock_get_save_filename(*args, **kwargs):
        return pdf_file, "PDF Files (*.pdf)"

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName", mock_get_save_filename
    )

    dialog._export_pdf()

    import os

    assert os.path.exists(pdf_file)
    assert os.path.getsize(pdf_file) > 0


def test_time_report_dialog_pdf_export_with_zero_hours(
    qtbot, fresh_db, tmp_path, monkeypatch
):
    """PDF export handles entries with zero hours gracefully."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    # Add entry with 0 minutes (edge case)
    fresh_db.add_time_log(_today(), proj_id, act_id, 0)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.from_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))

    dialog._run_report()

    pdf_file = str(tmp_path / "zero_hours.pdf")

    def mock_get_save_filename(*args, **kwargs):
        return pdf_file, "PDF Files (*.pdf)"

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName", mock_get_save_filename
    )

    # Should not crash
    dialog._export_pdf()


def test_time_report_dialog_csv_includes_total_row(
    qtbot, fresh_db, tmp_path, monkeypatch
):
    """CSV export includes total row at bottom."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 90)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.from_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))

    dialog._run_report()

    csv_file = str(tmp_path / "total_test.csv")

    def mock_get_save_filename(*args, **kwargs):
        return csv_file, "CSV Files (*.csv)"

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName", mock_get_save_filename
    )

    dialog._export_csv()

    with open(csv_file, "r") as f:
        lines = f.readlines()
        # Should have header, data row, blank, total row
        assert len(lines) >= 4
        # Last line should contain total
        assert "Total" in lines[-1] or "total" in lines[-1]


def test_time_report_dialog_pdf_chart_with_single_period(
    qtbot, fresh_db, tmp_path, monkeypatch
):
    """PDF chart renders correctly with single period."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 120)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.project_combo.setCurrentIndex(0)
    dialog.from_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))

    dialog._run_report()

    pdf_file = str(tmp_path / "single_period.pdf")

    def mock_get_save_filename(*args, **kwargs):
        return pdf_file, "PDF Files (*.pdf)"

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName", mock_get_save_filename
    )

    dialog._export_pdf()

    import os

    assert os.path.exists(pdf_file)


# ============================================================================
# Integration Tests
# ============================================================================


def test_full_workflow_add_project_activity_log_report(
    qtbot, fresh_db, tmp_path, monkeypatch
):
    """Test full workflow: create project, activity, log time, run report."""
    strings.load_strings("en")

    # 1. Create project via dialog
    manager = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(manager)

    def mock_get_text_project(parent, title, label, mode, default):
        return "Test Project", True

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text_project)
    manager._add_project()

    # 2. Create activity via dialog
    def mock_get_text_activity(parent, title, label, mode, default):
        return "Test Activity", True

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text_activity)
    manager._add_activity()

    manager.accept()

    # 3. Log time via dialog
    log_dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(log_dialog)

    log_dialog.project_combo.setCurrentIndex(0)
    log_dialog.activity_edit.setText("Test Activity")
    log_dialog.hours_spin.setValue(2.5)

    log_dialog._on_add_or_update()
    log_dialog.accept()

    # 4. Run report
    report_dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(report_dialog)

    report_dialog.project_combo.setCurrentIndex(0)
    report_dialog.from_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    report_dialog.to_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))

    report_dialog._run_report()

    # Verify report
    assert report_dialog.table.rowCount() == 1
    assert "Test Activity" in report_dialog.table.item(0, 2).text()
    assert (
        "2.5" in report_dialog.table.item(0, 4).text()
        or "2.50" in report_dialog.table.item(0, 4).text()
    )

    # 5. Export CSV
    csv_file = str(tmp_path / "workflow_test.csv")

    def mock_get_save_filename(*args, **kwargs):
        return csv_file, "CSV Files (*.csv)"

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName", mock_get_save_filename
    )

    report_dialog._export_csv()

    import os

    assert os.path.exists(csv_file)


def test_time_log_widget_with_multiple_projects_same_day(qtbot, fresh_db):
    """Widget correctly aggregates multiple projects on same day."""
    strings.load_strings("en")
    proj1_id = fresh_db.add_project("Alpha")
    proj2_id = fresh_db.add_project("Beta")
    proj3_id = fresh_db.add_project("Gamma")
    act_id = fresh_db.add_activity("Work")

    fresh_db.add_time_log(_today(), proj1_id, act_id, 30)
    fresh_db.add_time_log(_today(), proj2_id, act_id, 45)
    fresh_db.add_time_log(_today(), proj3_id, act_id, 60)

    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.toggle_btn.setChecked(True)
    widget._on_toggle(True)
    widget.set_current_date(_today())

    # Total should be 2.25 hours
    title = widget.toggle_btn.text()
    assert "2.25" in title or "2.2" in title

    # Summary should list all three projects
    summary = widget.summary_label.text()
    assert "Alpha" in summary
    assert "Beta" in summary
    assert "Gamma" in summary


def test_time_log_dialog_preserves_entry_id_through_update(qtbot, fresh_db):
    """Updating entry preserves entry ID."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)

    # Select and update
    dialog.table.selectRow(0)
    original_id = dialog._current_entry_id

    dialog.hours_spin.setValue(2.0)
    dialog._on_add_or_update()

    # Should still have same number of entries
    entries = fresh_db.time_log_for_date(_today())
    assert len(entries) == 1
    assert entries[0][0] == original_id


def test_db_time_log_sorting_by_project_activity_id(fresh_db):
    """time_log_for_date returns entries sorted correctly."""
    # Create in specific order to test sorting
    proj_z = fresh_db.add_project("ZZZ")
    proj_a = fresh_db.add_project("AAA")
    act_y = fresh_db.add_activity("YYY")
    act_x = fresh_db.add_activity("XXX")

    # Add in reverse alphabetical order
    fresh_db.add_time_log(_today(), proj_z, act_y, 10)
    fresh_db.add_time_log(_today(), proj_z, act_x, 20)
    fresh_db.add_time_log(_today(), proj_a, act_y, 30)
    fresh_db.add_time_log(_today(), proj_a, act_x, 40)

    entries = fresh_db.time_log_for_date(_today())

    # Should be sorted: AAA/XXX, AAA/YYY, ZZZ/XXX, ZZZ/YYY
    assert entries[0][3] == "AAA" and entries[0][5] == "XXX"
    assert entries[1][3] == "AAA" and entries[1][5] == "YYY"
    assert entries[2][3] == "ZZZ" and entries[2][5] == "XXX"
    assert entries[3][3] == "ZZZ" and entries[3][5] == "YYY"


def test_time_code_manager_add_activity_invalid_shows_warning(
    qtbot, fresh_db, monkeypatch
):
    """Test adding invalid activity shows warning."""
    strings.load_strings("en")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.show()

    def mock_get_text(parent, title, label, mode, default):
        return "Valid Name", True

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    # Force add_activity to raise ValueError
    original_add = fresh_db.add_activity

    def bad_add(name):
        raise ValueError("empty activity name")

    fresh_db.add_activity = bad_add

    warning_shown = {"shown": False}

    def mock_warning(*args):
        warning_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    dialog._add_activity()

    assert warning_shown["shown"]

    fresh_db.add_activity = original_add


def test_time_code_manager_rename_activity_to_duplicate(qtbot, fresh_db, monkeypatch):
    """Test renaming activity to existing name shows warning."""
    strings.load_strings("en")

    fresh_db.add_activity("Activity1")
    fresh_db.add_activity("Activity2")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.activity_list.setCurrentRow(0)

    def mock_get_text(parent, title, label, mode, default):
        return "Activity2", True

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    warning_shown = {"shown": False}

    def mock_warning(*args):
        warning_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    dialog._rename_activity()

    assert warning_shown["shown"]


def test_time_code_manager_rename_activity_cancelled(qtbot, fresh_db, monkeypatch):
    """Test cancelling activity rename."""
    strings.load_strings("en")

    fresh_db.add_activity("Original")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.activity_list.setCurrentRow(0)

    def mock_get_text(parent, title, label, mode, default):
        return "", False

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    dialog._rename_activity()

    # Should remain unchanged
    assert dialog.activity_list.item(0).text() == "Original"


def test_time_code_manager_rename_activity_same_name(qtbot, fresh_db, monkeypatch):
    """Test renaming activity to same name does nothing."""
    strings.load_strings("en")

    fresh_db.add_activity("SameName")

    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.activity_list.setCurrentRow(0)

    def mock_get_text(parent, title, label, mode, default):
        return "SameName", True

    monkeypatch.setattr(QInputDialog, "getText", mock_get_text)

    dialog._rename_activity()

    # Should still have one activity
    assert dialog.activity_list.count() == 1


def test_time_report_dialog_pdf_export_error_handling(
    qtbot, fresh_db, tmp_path, monkeypatch
):
    """Test PDF export handles exceptions gracefully."""
    strings.load_strings("en")

    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    fresh_db.add_time_log(_today(), proj_id, act_id, 60)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.project_combo.setCurrentIndex(0)
    from PySide6.QtCore import QDate

    dialog.from_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))

    dialog._run_report()

    pdf_file = str(tmp_path / "test.pdf")

    def mock_get_save_filename(*args, **kwargs):
        return pdf_file, "PDF Files (*.pdf)"

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName", mock_get_save_filename
    )

    # Mock QTextDocument.print_ to raise exception
    from PySide6.QtGui import QTextDocument

    original_print = QTextDocument.print_

    def bad_print(self, printer):
        raise Exception("Print error")

    monkeypatch.setattr(QTextDocument, "print_", bad_print)

    warning_shown = {"shown": False}

    def mock_warning(*args):
        warning_shown["shown"] = True

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    dialog._export_pdf()

    # Should show warning
    assert warning_shown["shown"]

    monkeypatch.setattr(QTextDocument, "print_", original_print)


def test_time_log_dialog_hours_conversion_edge_cases(qtbot, fresh_db):
    """Test edge cases in hours to minutes conversion."""
    strings.load_strings("en")

    fresh_db.add_project("Project")

    dialog = TimeLogDialog(fresh_db, _today())
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.project_combo.setCurrentIndex(0)
    dialog.activity_edit.setText("Activity")

    # Test 0 hours
    dialog.hours_spin.setValue(0.0)
    dialog._on_add_or_update()

    entries = fresh_db.time_log_for_date(_today())
    assert entries[-1][6] == 0

    # Test fractional hours that round
    dialog.hours_spin.setValue(0.333)  # ~20 minutes
    dialog._on_add_or_update()

    entries = fresh_db.time_log_for_date(_today())
    # Should round to nearest minute
    assert 19 <= entries[-1][6] <= 21


def test_time_report_dialog_pdf_with_no_activity_data(
    qtbot, fresh_db, tmp_path, monkeypatch
):
    """Test PDF export with report that has no data in bars (0 minutes)."""
    strings.load_strings("en")

    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    # Add entry with 0 minutes
    fresh_db.add_time_log(_today(), proj_id, act_id, 0)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.project_combo.setCurrentIndex(0)
    from PySide6.QtCore import QDate

    dialog.from_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))

    dialog._run_report()

    pdf_file = str(tmp_path / "zero_data.pdf")

    def mock_get_save_filename(*args, **kwargs):
        return pdf_file, "PDF Files (*.pdf)"

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName", mock_get_save_filename
    )

    # Should handle zero data without crashing
    dialog._export_pdf()

    import os

    assert os.path.exists(pdf_file)


def test_time_report_dialog_very_large_hours(qtbot, fresh_db):
    """Test handling very large hour values."""
    strings.load_strings("en")

    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")

    # Add entry with many hours
    large_minutes = 10000  # ~166 hours
    fresh_db.add_time_log(_today(), proj_id, act_id, large_minutes)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.project_combo.setCurrentIndex(0)
    from PySide6.QtCore import QDate

    dialog.from_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(_today(), "yyyy-MM-dd"))

    # Should handle large values
    dialog._run_report()

    # Check total label
    assert "166" in dialog.total_label.text() or "167" in dialog.total_label.text()


def test_time_log_widget_creation(qtbot, fresh_db):
    """TimeLogWidget can be created."""
    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)
    assert widget is not None
    assert not widget.toggle_btn.isChecked()
    assert not widget.body.isVisible()


def test_time_log_set_current_date(qtbot, fresh_db):
    """Test setting the current date on the time log widget."""
    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)

    today = date.today().isoformat()
    widget.set_current_date(today)

    # Verify the current date was set
    assert widget._current_date == today


def test_time_log_with_entry(qtbot, fresh_db):
    """Test time log widget with a time entry."""
    # Add a project
    proj_id = fresh_db.add_project("Test Project")
    # Add activity
    act_id = fresh_db.add_activity("Test Activity")

    # Add a time log entry
    today = date.today().isoformat()
    fresh_db.add_time_log(
        date_iso=today,
        project_id=proj_id,
        activity_id=act_id,
        minutes=150,
        note="Test note",
    )

    widget = TimeLogWidget(fresh_db)
    qtbot.addWidget(widget)
    widget.show()

    # Set the date to today
    widget.set_current_date(today)

    # Widget should have been created successfully
    assert widget is not None


def test_time_log_widget_open_dialog_log_only_when_no_date(qtbot, app, fresh_db):
    """Test _open_dialog_log_only when _current_date is None."""
    widget = TimeLogWidget(fresh_db, themes=None)
    qtbot.addWidget(widget)

    # Set current date to None
    widget._current_date = None

    # Click should return early without crashing
    widget._open_dialog_log_only()

    # No dialog should be shown


def test_time_log_widget_open_dialog_log_only_opens_dialog(qtbot, app, fresh_db):
    """Test _open_dialog_log_only opens TimeLogDialog."""
    widget = TimeLogWidget(fresh_db, themes=None)
    qtbot.addWidget(widget)

    # Set a valid date
    widget._current_date = "2024-01-15"

    # Mock TimeLogDialog
    mock_dialog = MagicMock()
    mock_dialog.exec.return_value = QDialog.Accepted

    with patch("bouquin.time_log.TimeLogDialog", return_value=mock_dialog):
        widget._open_dialog_log_only()

        # Dialog should have been created with correct parameters
        assert mock_dialog.exec.called


def test_time_log_widget_open_dialog_log_only_refreshes_when_collapsed(
    qtbot, app, fresh_db
):
    """Test that opening dialog updates summary when widget is collapsed."""
    widget = TimeLogWidget(fresh_db, themes=None)
    qtbot.addWidget(widget)
    widget._current_date = "2024-01-15"

    # Collapse the widget
    widget.toggle_btn.setChecked(False)

    # Mock TimeLogDialog
    mock_dialog = MagicMock()
    mock_dialog.exec.return_value = QDialog.Accepted

    with patch("bouquin.time_log.TimeLogDialog", return_value=mock_dialog):
        widget._open_dialog_log_only()

        # Should show collapsed hint
        assert (
            "collapsed" in widget.summary_label.text().lower()
            or widget.summary_label.text() != ""
        )


def test_time_log_dialog_log_entry_only_mode(qtbot, app, fresh_db):
    """Test TimeLogDialog in log_entry_only mode."""
    dialog = TimeLogDialog(
        fresh_db, "2024-01-15", log_entry_only=True, themes=None, close_after_add=True
    )
    qtbot.addWidget(dialog)

    # In log_entry_only mode, these should be hidden
    assert not dialog.delete_btn.isVisible()
    assert not dialog.report_btn.isVisible()
    assert not dialog.table.isVisible()


def test_time_log_dialog_log_entry_only_false(qtbot, app, fresh_db):
    """Test TimeLogDialog in normal mode (log_entry_only=False)."""
    dialog = TimeLogDialog(
        fresh_db, "2024-01-15", log_entry_only=False, themes=None, close_after_add=False
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    # In normal mode, these should be visible
    assert dialog.delete_btn.isVisible()
    assert dialog.report_btn.isVisible()
    assert dialog.table.isVisible()


def test_time_log_dialog_change_date_cancelled(qtbot, app, fresh_db):
    """Test _on_change_date_clicked when user cancels."""
    dialog = TimeLogDialog(fresh_db, "2024-01-15", themes=None)
    qtbot.addWidget(dialog)

    # Mock exec to return rejected
    with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
        original_date = dialog._date_iso
        dialog._on_change_date_clicked()

        # Date should not change when cancelled
        assert dialog._date_iso == original_date


def test_time_log_dialog_change_date_accepted(qtbot, app, fresh_db):
    """Test _on_change_date_clicked when user accepts (covers lines 410-450)."""
    dialog = TimeLogDialog(fresh_db, "2024-01-15", themes=None)
    qtbot.addWidget(dialog)

    # Mock exec to return accepted - the dialog will use whatever date is in the calendar
    with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
        # Just verify it doesn't crash - actual date may or may not change
        # depending on what the real QCalendarWidget selects
        dialog._on_change_date_clicked()

        # Dialog should still be functional
        assert dialog._date_iso is not None


def test_time_log_dialog_change_date_with_invalid_current_date(qtbot, app, fresh_db):
    """Test _on_change_date_clicked when current date is invalid (covers lines 410-412)."""
    dialog = TimeLogDialog(fresh_db, "invalid-date", themes=None)
    qtbot.addWidget(dialog)

    # Should fall back to current date without crashing
    with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
        dialog._on_change_date_clicked()


def test_time_log_dialog_change_date_with_themes(qtbot, app, fresh_db):
    """Test _on_change_date_clicked with theme manager (covers line 423-424)."""
    themes_mock = MagicMock()
    themes_mock.register_calendar = MagicMock()

    dialog = TimeLogDialog(fresh_db, "2024-01-15", themes=themes_mock)
    qtbot.addWidget(dialog)

    # Mock exec to return rejected
    with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
        dialog._on_change_date_clicked()

        # Theme should have been applied to calendar
        assert themes_mock.register_calendar.called


def test_time_log_dialog_table_item_changed_incomplete_row(qtbot, app, fresh_db):
    """Test _on_table_item_changed with incomplete row."""
    dialog = TimeLogDialog(fresh_db, "2024-01-15", themes=None)
    qtbot.addWidget(dialog)

    # Block signals to prevent Qt cleanup
    dialog.table.blockSignals(True)

    # Add incomplete row
    dialog.table.setRowCount(1)
    from PySide6.QtWidgets import QTableWidgetItem

    # Only add project item, missing others
    proj_item = QTableWidgetItem("Project")
    dialog.table.setItem(0, 0, proj_item)

    # Call _on_table_item_changed
    dialog._on_table_item_changed(proj_item)

    dialog.table.blockSignals(False)

    # Should return early without crashing (covers lines 556-558)


def test_time_log_dialog_table_item_changed_creates_new_project(qtbot, app, fresh_db):
    """Test _on_table_item_changed creating a new project on the fly."""
    dialog = TimeLogDialog(fresh_db, "2024-01-15", themes=None)
    qtbot.addWidget(dialog)

    # Block signals to prevent Qt cleanup
    dialog.table.blockSignals(True)

    # Add a complete row with new project name
    dialog.table.setRowCount(1)
    from PySide6.QtWidgets import QTableWidgetItem

    proj_item = QTableWidgetItem("Brand New Project")
    proj_item.setData(Qt.ItemDataRole.UserRole, None)  # No entry ID
    act_item = QTableWidgetItem("Activity")
    note_item = QTableWidgetItem("Note")
    hours_item = QTableWidgetItem("2.5")

    dialog.table.setItem(0, 0, proj_item)
    dialog.table.setItem(0, 1, act_item)
    dialog.table.setItem(0, 2, note_item)
    dialog.table.setItem(0, 3, hours_item)

    # Call _on_table_item_changed
    with patch.object(dialog, "_on_add_or_update"):
        dialog._on_table_item_changed(proj_item)

        # Should have created project and called add/update
        projects = fresh_db.list_projects()
        project_names = [name for _, name in projects]
        assert "Brand New Project" in project_names

    dialog.table.blockSignals(False)


def test_time_log_dialog_table_item_changed_without_note(qtbot, app, fresh_db):
    """Test _on_table_item_changed when note_item is None."""
    dialog = TimeLogDialog(fresh_db, "2024-01-15", themes=None)
    qtbot.addWidget(dialog)

    # Block signals to prevent Qt cleanup
    dialog.table.blockSignals(True)

    # Add row without note
    dialog.table.setRowCount(1)
    from PySide6.QtWidgets import QTableWidgetItem

    proj_item = QTableWidgetItem("Project")
    proj_item.setData(Qt.ItemDataRole.UserRole, None)
    act_item = QTableWidgetItem("Activity")
    hours_item = QTableWidgetItem("1.0")

    dialog.table.setItem(0, 0, proj_item)
    dialog.table.setItem(0, 1, act_item)
    # Note: Don't set note_item (leave as None)
    dialog.table.setItem(0, 3, hours_item)

    # Call _on_table_item_changed
    with patch.object(dialog, "_on_add_or_update"):
        dialog._on_table_item_changed(proj_item)

        # Should handle None note gracefully (covers line 567)
        assert dialog.note.text() == ""

    dialog.table.blockSignals(False)


def test_time_log_dialog_table_item_changed_sets_button_state_for_new_entry(
    qtbot, app, fresh_db
):
    """Test that _on_table_item_changed sets correct button state for new entry."""
    dialog = TimeLogDialog(fresh_db, "2024-01-15", themes=None)
    qtbot.addWidget(dialog)

    # Block signals to prevent Qt cleanup
    dialog.table.blockSignals(True)

    # Add row without entry ID (new entry)
    dialog.table.setRowCount(1)
    from PySide6.QtWidgets import QTableWidgetItem

    proj_item = QTableWidgetItem("Project")
    proj_item.setData(Qt.ItemDataRole.UserRole, None)  # No entry ID
    act_item = QTableWidgetItem("Activity")
    hours_item = QTableWidgetItem("1.0")

    dialog.table.setItem(0, 0, proj_item)
    dialog.table.setItem(0, 1, act_item)
    dialog.table.setItem(0, 3, hours_item)

    with patch.object(dialog, "_on_add_or_update"):
        dialog._on_table_item_changed(proj_item)

        # Delete button should be disabled for new entry (covers lines 601-603)
        assert not dialog.delete_btn.isEnabled()

    dialog.table.blockSignals(False)


def test_time_log_dialog_table_item_changed_sets_button_state_for_existing_entry(
    qtbot, app, fresh_db
):
    """Test that _on_table_item_changed sets correct button state for existing entry."""
    # Add a time log entry first
    proj_id = fresh_db.add_project("Test Project")
    act_id = fresh_db.add_activity("Activity")
    entry_id = fresh_db.add_time_log(
        "2024-01-15", proj_id, act_id, 120, "Note"
    )  # 120 minutes = 2 hours

    dialog = TimeLogDialog(fresh_db, "2024-01-15", themes=None)
    qtbot.addWidget(dialog)

    # Block signals to prevent Qt cleanup
    dialog.table.blockSignals(True)

    # Add row with entry ID
    dialog.table.setRowCount(1)
    from PySide6.QtWidgets import QTableWidgetItem

    proj_item = QTableWidgetItem("Test Project")
    proj_item.setData(Qt.ItemDataRole.UserRole, entry_id)
    act_item = QTableWidgetItem("Activity")
    hours_item = QTableWidgetItem("2.0")

    dialog.table.setItem(0, 0, proj_item)
    dialog.table.setItem(0, 1, act_item)
    dialog.table.setItem(0, 3, hours_item)

    with patch.object(dialog, "_on_add_or_update"):
        dialog._on_table_item_changed(proj_item)

        # Delete button should be enabled for existing entry (covers lines 604-606)
        assert dialog.delete_btn.isEnabled()

    dialog.table.blockSignals(False)


def test_time_log_dialog_table_item_changed_finds_existing_project_by_name(
    qtbot, app, fresh_db
):
    """Test _on_table_item_changed finding existing project by name."""
    proj_id = fresh_db.add_project("Existing Project")

    dialog = TimeLogDialog(fresh_db, "2024-01-15", themes=None)
    qtbot.addWidget(dialog)

    # Block signals to prevent Qt cleanup
    dialog.table.blockSignals(True)

    # Add row with existing project name
    dialog.table.setRowCount(1)
    from PySide6.QtWidgets import QTableWidgetItem

    proj_item = QTableWidgetItem("Existing Project")
    proj_item.setData(Qt.ItemDataRole.UserRole, None)
    act_item = QTableWidgetItem("Activity")
    hours_item = QTableWidgetItem("1.0")

    dialog.table.setItem(0, 0, proj_item)
    dialog.table.setItem(0, 1, act_item)
    dialog.table.setItem(0, 3, hours_item)

    with patch.object(dialog, "_on_add_or_update"):
        dialog._on_table_item_changed(proj_item)

        # Should find and select existing project (covers lines 571-580)
        assert dialog.project_combo.currentData() == proj_id

    dialog.table.blockSignals(False)


def test_time_report_dialog_initialization(qtbot, app, fresh_db):
    """Test TimeReportDialog initialization."""
    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    # Should initialize without crashing
    assert dialog is not None


def test_time_code_manager_dialog_initialization(qtbot, app, fresh_db):
    """Test TimeCodeManagerDialog initialization."""
    dialog = TimeCodeManagerDialog(fresh_db)
    qtbot.addWidget(dialog)

    # Should initialize without crashing
    assert dialog is not None


def test_time_code_manager_dialog_with_focus_tab(qtbot, app, fresh_db):
    """Test TimeCodeManagerDialog with initial tab focus."""
    # Test with projects tab
    dialog = TimeCodeManagerDialog(fresh_db, focus_tab="projects")
    qtbot.addWidget(dialog)
    assert dialog.tabs.currentIndex() == 0

    # Test with activities tab
    dialog2 = TimeCodeManagerDialog(fresh_db, focus_tab="activities")
    qtbot.addWidget(dialog2)
    assert dialog2.tabs.currentIndex() == 1


def test_time_report_no_grouping_returns_each_entry_and_note(fresh_db):
    """Granularity 'none' returns one row per entry and includes notes."""
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    date = _today()

    fresh_db.add_time_log(date, proj_id, act_id, 60, note="First")
    fresh_db.add_time_log(date, proj_id, act_id, 30, note="Second")

    report = fresh_db.time_report(proj_id, date, date, "none")

    # Two separate rows, not aggregated.
    assert len(report) == 2

    # Each row is (period, activity_name, note, total_minutes)
    periods = {r[0] for r in report}
    activities = {r[1] for r in report}
    notes = {r[2] for r in report}
    minutes = sorted(r[3] for r in report)

    assert periods == {date}
    assert activities == {"Activity"}
    assert notes == {"First", "Second"}
    assert minutes == [30, 60]


def test_time_report_dialog_granularity_none_shows_each_entry_and_notes(
    qtbot, fresh_db
):
    """'Don't group' granularity shows one row per log entry and includes notes."""
    strings.load_strings("en")
    proj_id = fresh_db.add_project("Project")
    act_id = fresh_db.add_activity("Activity")
    date = _today()

    fresh_db.add_time_log(date, proj_id, act_id, 60, note="First")
    fresh_db.add_time_log(date, proj_id, act_id, 30, note="Second")

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    # Select the concrete project (index 0 is "All projects")
    dialog.project_combo.setCurrentIndex(1)
    dialog.from_date.setDate(QDate.fromString(date, "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString(date, "yyyy-MM-dd"))

    idx_none = dialog.granularity.findData("none")
    assert idx_none != -1
    dialog.granularity.setCurrentIndex(idx_none)

    dialog._run_report()

    # Two rows, not aggregated
    assert dialog.table.rowCount() == 2

    # Notes in column 3
    notes = {dialog.table.item(row, 3).text() for row in range(dialog.table.rowCount())}
    assert "First" in notes
    assert "Second" in notes

    # Hours in last column (index 4) when not grouped
    hours = [dialog.table.item(row, 4).text() for row in range(dialog.table.rowCount())]
    assert any("1.00" in h or "1.0" in h for h in hours)
    assert any("0.50" in h or "0.5" in h for h in hours)
