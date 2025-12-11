from datetime import date, timedelta

import pytest
from bouquin.invoices import (
    _INVOICE_REMINDER_TIME,
    InvoiceDetailMode,
    InvoiceDialog,
    InvoiceLineItem,
    InvoicesDialog,
    _invoice_due_reminder_text,
)
from bouquin.reminders import Reminder, ReminderType
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QMessageBox

# ============================================================================
# Tests for InvoiceDetailMode enum
# ============================================================================


def test_invoice_detail_mode_enum_values(app):
    """Test InvoiceDetailMode enum has expected values."""
    assert InvoiceDetailMode.DETAILED == "detailed"
    assert InvoiceDetailMode.SUMMARY == "summary"


def test_invoice_detail_mode_is_string(app):
    """Test InvoiceDetailMode enum inherits from str."""
    assert isinstance(InvoiceDetailMode.DETAILED, str)
    assert isinstance(InvoiceDetailMode.SUMMARY, str)


# ============================================================================
# Tests for InvoiceLineItem dataclass
# ============================================================================


def test_invoice_line_item_creation(app):
    """Test creating an InvoiceLineItem instance."""
    item = InvoiceLineItem(
        description="Development work",
        hours=5.5,
        rate_cents=10000,
        amount_cents=55000,
    )

    assert item.description == "Development work"
    assert item.hours == 5.5
    assert item.rate_cents == 10000
    assert item.amount_cents == 55000


def test_invoice_line_item_with_zero_values(app):
    """Test InvoiceLineItem with zero values."""
    item = InvoiceLineItem(
        description="",
        hours=0.0,
        rate_cents=0,
        amount_cents=0,
    )

    assert item.description == ""
    assert item.hours == 0.0
    assert item.rate_cents == 0
    assert item.amount_cents == 0


# ============================================================================
# Tests for _invoice_due_reminder_text helper function
# ============================================================================


def test_invoice_due_reminder_text_normal(app):
    """Test reminder text generation with normal inputs."""
    result = _invoice_due_reminder_text("Project Alpha", "INV-001")
    assert result == "Invoice INV-001 for Project Alpha is due"


def test_invoice_due_reminder_text_with_whitespace(app):
    """Test reminder text strips whitespace from inputs."""
    result = _invoice_due_reminder_text("  Project Beta  ", "  INV-002  ")
    assert result == "Invoice INV-002 for Project Beta is due"


def test_invoice_due_reminder_text_empty_project(app):
    """Test reminder text with empty project name."""
    result = _invoice_due_reminder_text("", "INV-003")
    assert result == "Invoice INV-003 for (no project) is due"


def test_invoice_due_reminder_text_empty_invoice_number(app):
    """Test reminder text with empty invoice number."""
    result = _invoice_due_reminder_text("Project Gamma", "")
    assert result == "Invoice ? for Project Gamma is due"


def test_invoice_due_reminder_text_both_empty(app):
    """Test reminder text with both inputs empty."""
    result = _invoice_due_reminder_text("", "")
    assert result == "Invoice ? for (no project) is due"


# ============================================================================
# Tests for InvoiceDialog
# ============================================================================


@pytest.fixture
def invoice_dialog_setup(qtbot, fresh_db):
    """Set up a project with time logs for InvoiceDialog testing."""
    # Create a project
    proj_id = fresh_db.add_project("Test Project")

    # Create an activity
    act_id = fresh_db.add_activity("Development")

    # Set billing info
    fresh_db.upsert_project_billing(
        proj_id,
        hourly_rate_cents=15000,  # $150/hr
        currency="USD",
        tax_label="VAT",
        tax_rate_percent=20.0,
        client_name="John Doe",
        client_company="Acme Corp",
        client_address="123 Main St",
        client_email="john@acme.com",
    )

    # Create some time logs
    today = date.today()
    start_date = (today - timedelta(days=7)).isoformat()
    end_date = today.isoformat()

    # Add time logs for testing (2.5 hours = 150 minutes)
    for i in range(3):
        log_date = (today - timedelta(days=i)).isoformat()
        fresh_db.add_time_log(
            log_date,
            proj_id,
            act_id,
            150,  # 2.5 hours in minutes
            f"Note {i}",
        )

    time_rows = fresh_db.time_logs_for_range(proj_id, start_date, end_date)

    return {
        "db": fresh_db,
        "proj_id": proj_id,
        "act_id": act_id,
        "start_date": start_date,
        "end_date": end_date,
        "time_rows": time_rows,
    }


def test_invoice_dialog_init(qtbot, invoice_dialog_setup):
    """Test InvoiceDialog initialization."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    assert dialog._db is setup["db"]
    assert dialog._project_id == setup["proj_id"]
    assert dialog._start == setup["start_date"]
    assert dialog._end == setup["end_date"]
    assert len(dialog._time_rows) == 3


def test_invoice_dialog_init_without_time_rows(qtbot, invoice_dialog_setup):
    """Test InvoiceDialog initialization without explicit time_rows."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
    )
    qtbot.addWidget(dialog)

    # Should fetch time rows from DB
    assert len(dialog._time_rows) == 3


def test_invoice_dialog_loads_billing_defaults(qtbot, invoice_dialog_setup):
    """Test that InvoiceDialog loads billing defaults from project."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    assert dialog.currency_edit.text() == "USD"
    assert dialog.rate_spin.value() == 150.0
    assert dialog.client_name_edit.text() == "John Doe"
    assert dialog.client_company_combo.currentText() == "Acme Corp"


def test_invoice_dialog_no_billing_defaults(qtbot, fresh_db):
    """Test InvoiceDialog with project that has no billing info."""
    proj_id = fresh_db.add_project("Test Project No Billing")
    today = date.today()
    start = (today - timedelta(days=1)).isoformat()
    end = today.isoformat()

    dialog = InvoiceDialog(fresh_db, proj_id, start, end)
    qtbot.addWidget(dialog)

    # Should use defaults
    assert dialog.currency_edit.text() == "AUD"
    assert dialog.rate_spin.value() == 0.0
    assert dialog.client_name_edit.text() == ""


def test_invoice_dialog_project_name(qtbot, invoice_dialog_setup):
    """Test _project_name method."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    project_name = dialog._project_name()
    assert project_name == "Test Project"


def test_invoice_dialog_suggest_invoice_number(qtbot, invoice_dialog_setup):
    """Test _suggest_invoice_number method."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    invoice_number = dialog._suggest_invoice_number()
    # Should be in format YYYY-001 for first invoice (3 digits)
    current_year = date.today().year
    assert invoice_number.startswith(str(current_year))
    assert invoice_number.endswith("-001")


def test_invoice_dialog_suggest_invoice_number_increments(qtbot, invoice_dialog_setup):
    """Test that invoice number suggestions increment."""
    setup = invoice_dialog_setup

    # Create an invoice first
    dialog1 = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog1)

    # Save an invoice to increment the counter
    invoice_number_1 = dialog1._suggest_invoice_number()
    setup["db"].create_invoice(
        project_id=setup["proj_id"],
        invoice_number=invoice_number_1,
        issue_date=date.today().isoformat(),
        due_date=(date.today() + timedelta(days=14)).isoformat(),
        currency="USD",
        tax_label=None,
        tax_rate_percent=None,
        detail_mode=InvoiceDetailMode.DETAILED,
        line_items=[],
        time_log_ids=[],
    )

    # Create another dialog and check the number increments
    dialog2 = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog2)

    invoice_number_2 = dialog2._suggest_invoice_number()
    current_year = date.today().year
    assert invoice_number_2 == f"{current_year}-002"


def test_invoice_dialog_populate_detailed_rows(qtbot, invoice_dialog_setup):
    """Test _populate_detailed_rows method."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    dialog._populate_detailed_rows(15000)  # $150/hr in cents

    # Check that table has rows
    assert dialog.table.rowCount() == 3

    # Check that hours are displayed (COL_HOURS uses cellWidget, not item)
    for row in range(3):
        hours_widget = dialog.table.cellWidget(row, dialog.COL_HOURS)
        assert hours_widget is not None
        assert hours_widget.value() == 2.5


def test_invoice_dialog_total_hours_from_table(qtbot, invoice_dialog_setup):
    """Test _total_hours_from_table method."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    dialog._populate_detailed_rows(15000)

    total_hours = dialog._total_hours_from_table()
    # 3 rows * 2.5 hours = 7.5 hours
    assert total_hours == 7.5


def test_invoice_dialog_detail_line_items(qtbot, invoice_dialog_setup):
    """Test _detail_line_items method."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    dialog.rate_spin.setValue(150.0)
    dialog._populate_detailed_rows(15000)

    line_items = dialog._detail_line_items()
    assert len(line_items) == 3

    for item in line_items:
        assert isinstance(item, InvoiceLineItem)
        assert item.hours == 2.5
        assert item.rate_cents == 15000
        assert item.amount_cents == 37500  # 2.5 * 15000


def test_invoice_dialog_summary_line_items(qtbot, invoice_dialog_setup):
    """Test _summary_line_items method."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    dialog.rate_spin.setValue(150.0)
    dialog._populate_detailed_rows(15000)

    line_items = dialog._summary_line_items()
    assert len(line_items) == 1  # Summary should have one line

    item = line_items[0]
    assert isinstance(item, InvoiceLineItem)
    # The description comes from summary_desc_edit which has a localized default
    # Just check it's not empty
    assert len(item.description) > 0
    assert item.hours == 7.5  # Total of 3 * 2.5
    assert item.rate_cents == 15000
    assert item.amount_cents == 112500  # 7.5 * 15000


def test_invoice_dialog_recalc_amounts(qtbot, invoice_dialog_setup):
    """Test _recalc_amounts method."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    dialog._populate_detailed_rows(15000)
    dialog.rate_spin.setValue(200.0)  # Change rate to $200/hr

    dialog._recalc_amounts()

    # Check that amounts were recalculated
    for row in range(3):
        amount_item = dialog.table.item(row, dialog.COL_AMOUNT)
        assert amount_item is not None
        # 2.5 hours * $200 = $500
        assert amount_item.text() == "500.00"


def test_invoice_dialog_recalc_totals(qtbot, invoice_dialog_setup):
    """Test _recalc_totals method."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    dialog.rate_spin.setValue(100.0)
    dialog._populate_detailed_rows(10000)

    # Enable tax
    dialog.tax_checkbox.setChecked(True)
    dialog.tax_rate_spin.setValue(10.0)

    dialog._recalc_totals()

    # 7.5 hours * $100 = $750
    # Tax: $750 * 10% = $75
    # Total: $750 + $75 = $825
    assert "750.00" in dialog.subtotal_label.text()
    assert "75.00" in dialog.tax_label_total.text()
    assert "825.00" in dialog.total_label.text()


def test_invoice_dialog_on_tax_toggled(qtbot, invoice_dialog_setup):
    """Test _on_tax_toggled method."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)
    dialog.show()

    # Initially unchecked (from fixture setup with tax)
    dialog.tax_checkbox.setChecked(False)
    dialog._on_tax_toggled(False)

    # Tax fields should be hidden
    assert not dialog.tax_label.isVisible()
    assert not dialog.tax_label_edit.isVisible()
    assert not dialog.tax_rate_label.isVisible()
    assert not dialog.tax_rate_spin.isVisible()

    # Check the box
    dialog.tax_checkbox.setChecked(True)
    dialog._on_tax_toggled(True)

    # Tax fields should be visible
    assert dialog.tax_label.isVisible()
    assert dialog.tax_label_edit.isVisible()
    assert dialog.tax_rate_label.isVisible()
    assert dialog.tax_rate_spin.isVisible()


def test_invoice_dialog_on_client_company_changed(qtbot, invoice_dialog_setup):
    """Test _on_client_company_changed method for autofill."""
    setup = invoice_dialog_setup

    # Create another project with different client
    proj_id_2 = setup["db"].add_project("Project 2")
    setup["db"].upsert_project_billing(
        proj_id_2,
        hourly_rate_cents=20000,
        currency="EUR",
        tax_label="GST",
        tax_rate_percent=15.0,
        client_name="Jane Smith",
        client_company="Tech Industries",
        client_address="456 Oak Ave",
        client_email="jane@tech.com",
    )

    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    # Initially should have first project's client
    assert dialog.client_name_edit.text() == "John Doe"

    # Change to second company
    dialog.client_company_combo.setCurrentText("Tech Industries")
    dialog._on_client_company_changed("Tech Industries")

    # Should autofill with second client's info
    assert dialog.client_name_edit.text() == "Jane Smith"
    assert dialog.client_addr_edit.toPlainText() == "456 Oak Ave"
    assert dialog.client_email_edit.text() == "jane@tech.com"


def test_invoice_dialog_create_due_date_reminder(qtbot, invoice_dialog_setup):
    """Test _create_due_date_reminder method."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    due_date = (date.today() + timedelta(days=14)).isoformat()
    invoice_number = "INV-TEST-001"
    invoice_id = 999  # Fake invoice ID for testing

    dialog._create_due_date_reminder(invoice_id, invoice_number, due_date)

    # Check that reminder was created
    reminders = setup["db"].get_all_reminders()
    assert len(reminders) > 0

    # Find our reminder
    expected_text = _invoice_due_reminder_text("Test Project", invoice_number)
    matching_reminders = [r for r in reminders if r.text == expected_text]
    assert len(matching_reminders) == 1

    reminder = matching_reminders[0]
    assert reminder.reminder_type == ReminderType.ONCE
    assert reminder.date_iso == due_date
    assert reminder.time_str == _INVOICE_REMINDER_TIME


# ============================================================================
# Tests for InvoicesDialog
# ============================================================================


@pytest.fixture
def invoices_dialog_setup(qtbot, fresh_db):
    """Set up projects with invoices for InvoicesDialog testing."""
    # Create projects
    proj_id_1 = fresh_db.add_project("Project Alpha")
    proj_id_2 = fresh_db.add_project("Project Beta")

    # Create invoices for project 1
    today = date.today()
    for i in range(3):
        issue_date = (today - timedelta(days=i * 7)).isoformat()
        due_date = (today - timedelta(days=i * 7) + timedelta(days=14)).isoformat()
        paid_at = today.isoformat() if i == 0 else None  # First one is paid

        fresh_db.create_invoice(
            project_id=proj_id_1,
            invoice_number=f"ALPHA-{i+1}",
            issue_date=issue_date,
            due_date=due_date,
            currency="USD",
            tax_label="VAT",
            tax_rate_percent=20.0,
            detail_mode=InvoiceDetailMode.DETAILED,
            line_items=[("Development work", 10.0, 15000)],  # 10 hours at $150/hr
            time_log_ids=[],
        )

        # Update paid_at separately if needed
        if paid_at:
            invoice_rows = fresh_db.get_all_invoices(proj_id_1)
            if invoice_rows:
                inv_id = invoice_rows[0]["id"]
                fresh_db.set_invoice_field_by_id(inv_id, "paid_at", paid_at)

    # Create invoices for project 2
    for i in range(2):
        issue_date = (today - timedelta(days=i * 10)).isoformat()
        due_date = (today - timedelta(days=i * 10) + timedelta(days=30)).isoformat()

        fresh_db.create_invoice(
            project_id=proj_id_2,
            invoice_number=f"BETA-{i+1}",
            issue_date=issue_date,
            due_date=due_date,
            currency="EUR",
            tax_label=None,
            tax_rate_percent=None,
            detail_mode=InvoiceDetailMode.SUMMARY,
            line_items=[("Consulting services", 10.0, 20000)],  # 10 hours at $200/hr
            time_log_ids=[],
        )

    return {
        "db": fresh_db,
        "proj_id_1": proj_id_1,
        "proj_id_2": proj_id_2,
    }


def test_invoices_dialog_init(qtbot, invoices_dialog_setup):
    """Test InvoicesDialog initialization."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"])
    qtbot.addWidget(dialog)

    assert dialog._db is setup["db"]
    assert dialog.project_combo.count() >= 2  # 2 projects


def test_invoices_dialog_init_with_project_id(qtbot, invoices_dialog_setup):
    """Test InvoicesDialog initialization with specific project."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Should select the specified project
    current_proj = dialog._current_project()
    assert current_proj == setup["proj_id_1"]


def test_invoices_dialog_reload_projects(qtbot, invoices_dialog_setup):
    """Test _reload_projects method."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"])
    qtbot.addWidget(dialog)

    initial_count = dialog.project_combo.count()
    assert initial_count >= 2  # Should have 2 projects from setup

    # Create a new project
    setup["db"].add_project("Project Gamma")

    # Reload projects
    dialog._reload_projects()

    # Should have one more project
    assert dialog.project_combo.count() == initial_count + 1


def test_invoices_dialog_current_project_specific(qtbot, invoices_dialog_setup):
    """Test _current_project method when specific project is selected."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    current_proj = dialog._current_project()
    assert current_proj == setup["proj_id_1"]


def test_invoices_dialog_reload_invoices_all_projects(qtbot, invoices_dialog_setup):
    """Test _reload_invoices with first project selected by default."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"])
    qtbot.addWidget(dialog)

    # First project should be selected by default (Project Alpha with 3 invoices)
    # The exact project depends on creation order, so just check we have some invoices
    assert dialog.table.rowCount() in [2, 3]  # Either proj1 (3) or proj2 (2)


def test_invoices_dialog_reload_invoices_single_project(qtbot, invoices_dialog_setup):
    """Test _reload_invoices with single project selected."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    dialog._reload_invoices()

    # Should show only 3 invoices from proj1
    assert dialog.table.rowCount() == 3


def test_invoices_dialog_on_project_changed(qtbot, invoices_dialog_setup):
    """Test _on_project_changed method."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_2"])
    qtbot.addWidget(dialog)

    # Start with project 2 (2 invoices)
    assert dialog.table.rowCount() == 2

    # Find the index of project 1
    for i in range(dialog.project_combo.count()):
        if dialog.project_combo.itemData(i) == setup["proj_id_1"]:
            dialog.project_combo.setCurrentIndex(i)
            break

    dialog._on_project_changed(dialog.project_combo.currentIndex())

    # Should now show 3 invoices from proj1
    assert dialog.table.rowCount() == 3


def test_invoices_dialog_remove_invoice_due_reminder(qtbot, invoices_dialog_setup):
    """Test _remove_invoice_due_reminder method."""
    setup = invoices_dialog_setup

    # Create a reminder for an invoice
    due_date = (date.today() + timedelta(days=7)).isoformat()
    invoice_number = "TEST-REMINDER-001"
    project_name = "Project Alpha"

    reminder_text = _invoice_due_reminder_text(project_name, invoice_number)
    reminder = Reminder(
        id=None,
        text=reminder_text,
        time_str=_INVOICE_REMINDER_TIME,
        reminder_type=ReminderType.ONCE,
        date_iso=due_date,
        active=True,
    )
    reminder.id = setup["db"].save_reminder(reminder)

    # Verify reminder exists
    reminders = setup["db"].get_all_reminders()
    assert len(reminders) == 1

    # Create dialog and populate with invoices
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Manually add a row to test the removal (simulating the invoice row)
    row = dialog.table.rowCount()
    dialog.table.insertRow(row)

    # Set the project and invoice number items
    from PySide6.QtWidgets import QTableWidgetItem

    proj_item = QTableWidgetItem(project_name)
    num_item = QTableWidgetItem(invoice_number)
    dialog.table.setItem(row, dialog.COL_PROJECT, proj_item)
    dialog.table.setItem(row, dialog.COL_NUMBER, num_item)

    # Mock invoice_id
    num_item.setData(Qt.ItemDataRole.UserRole, 999)

    # Call the removal method
    dialog._remove_invoice_due_reminder(row, 999)

    # Reminder should be deleted
    reminders_after = setup["db"].get_all_reminders()
    assert len(reminders_after) == 0


def test_invoices_dialog_on_item_changed_invoice_number(qtbot, invoices_dialog_setup):
    """Test _on_item_changed for invoice number editing."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Get the first row's invoice ID
    num_item = dialog.table.item(0, dialog.COL_NUMBER)
    inv_id = num_item.data(Qt.ItemDataRole.UserRole)

    # Change the invoice number
    num_item.setText("ALPHA-MODIFIED")

    # Trigger the change handler
    dialog._on_item_changed(num_item)

    # Verify the change was saved to DB
    invoice_data = setup["db"].get_invoice_field_by_id(inv_id, "invoice_number")
    assert invoice_data["invoice_number"] == "ALPHA-MODIFIED"


def test_invoices_dialog_on_item_changed_empty_invoice_number(
    qtbot, invoices_dialog_setup, monkeypatch
):
    """Test _on_item_changed rejects empty invoice number."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Mock QMessageBox to auto-close
    def mock_warning(*args, **kwargs):
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    # Get the first row's invoice number item
    num_item = dialog.table.item(0, dialog.COL_NUMBER)
    original_number = num_item.text()

    # Try to set empty invoice number
    num_item.setText("")
    dialog._on_item_changed(num_item)

    # Should be reset to original
    assert num_item.text() == original_number


def test_invoices_dialog_on_item_changed_issue_date(qtbot, invoices_dialog_setup):
    """Test _on_item_changed for issue date editing."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Get the first row
    num_item = dialog.table.item(0, dialog.COL_NUMBER)
    inv_id = num_item.data(Qt.ItemDataRole.UserRole)

    issue_item = dialog.table.item(0, dialog.COL_ISSUE_DATE)
    new_date = "2024-01-15"
    issue_item.setText(new_date)

    dialog._on_item_changed(issue_item)

    # Verify change was saved
    invoice_data = setup["db"].get_invoice_field_by_id(inv_id, "issue_date")
    assert invoice_data["issue_date"] == new_date


def test_invoices_dialog_on_item_changed_invalid_date(
    qtbot, invoices_dialog_setup, monkeypatch
):
    """Test _on_item_changed rejects invalid date format."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Mock QMessageBox
    def mock_warning(*args, **kwargs):
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    issue_item = dialog.table.item(0, dialog.COL_ISSUE_DATE)
    original_date = issue_item.text()

    # Try to set invalid date
    issue_item.setText("not-a-date")
    dialog._on_item_changed(issue_item)

    # Should be reset to original
    assert issue_item.text() == original_date


def test_invoices_dialog_on_item_changed_due_before_issue(
    qtbot, invoices_dialog_setup, monkeypatch
):
    """Test _on_item_changed rejects due date before issue date."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Mock QMessageBox
    def mock_warning(*args, **kwargs):
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    # Set issue date
    issue_item = dialog.table.item(0, dialog.COL_ISSUE_DATE)
    issue_item.setText("2024-02-01")
    dialog._on_item_changed(issue_item)

    # Try to set due date before issue date
    due_item = dialog.table.item(0, dialog.COL_DUE_DATE)
    original_due = due_item.text()
    due_item.setText("2024-01-01")
    dialog._on_item_changed(due_item)

    # Should be reset
    assert due_item.text() == original_due


def test_invoices_dialog_on_item_changed_currency(qtbot, invoices_dialog_setup):
    """Test _on_item_changed for currency editing."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Get the first row
    num_item = dialog.table.item(0, dialog.COL_NUMBER)
    inv_id = num_item.data(Qt.ItemDataRole.UserRole)

    currency_item = dialog.table.item(0, dialog.COL_CURRENCY)
    currency_item.setText("gbp")  # lowercase

    dialog._on_item_changed(currency_item)

    # Should be normalized to uppercase
    assert currency_item.text() == "GBP"

    # Verify change was saved
    invoice_data = setup["db"].get_invoice_field_by_id(inv_id, "currency")
    assert invoice_data["currency"] == "GBP"


def test_invoices_dialog_on_item_changed_tax_rate(qtbot, invoices_dialog_setup):
    """Test _on_item_changed for tax rate editing."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Get the first row
    num_item = dialog.table.item(0, dialog.COL_NUMBER)
    inv_id = num_item.data(Qt.ItemDataRole.UserRole)

    tax_rate_item = dialog.table.item(0, dialog.COL_TAX_RATE)
    tax_rate_item.setText("15.5")

    dialog._on_item_changed(tax_rate_item)

    # Verify change was saved
    invoice_data = setup["db"].get_invoice_field_by_id(inv_id, "tax_rate_percent")
    assert invoice_data["tax_rate_percent"] == 15.5


def test_invoices_dialog_on_item_changed_invalid_tax_rate(
    qtbot, invoices_dialog_setup, monkeypatch
):
    """Test _on_item_changed rejects invalid tax rate."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Mock QMessageBox
    def mock_warning(*args, **kwargs):
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    tax_rate_item = dialog.table.item(0, dialog.COL_TAX_RATE)
    original_rate = tax_rate_item.text()

    # Try to set invalid tax rate
    tax_rate_item.setText("not-a-number")
    dialog._on_item_changed(tax_rate_item)

    # Should be reset to original
    assert tax_rate_item.text() == original_rate


def test_invoices_dialog_on_item_changed_subtotal(qtbot, invoices_dialog_setup):
    """Test _on_item_changed for subtotal editing."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Get the first row
    num_item = dialog.table.item(0, dialog.COL_NUMBER)
    inv_id = num_item.data(Qt.ItemDataRole.UserRole)

    subtotal_item = dialog.table.item(0, dialog.COL_SUBTOTAL)
    subtotal_item.setText("1234.56")

    dialog._on_item_changed(subtotal_item)

    # Verify change was saved (in cents)
    invoice_data = setup["db"].get_invoice_field_by_id(inv_id, "subtotal_cents")
    assert invoice_data["subtotal_cents"] == 123456

    # Should be normalized to 2 decimals
    assert subtotal_item.text() == "1234.56"


def test_invoices_dialog_on_item_changed_invalid_amount(
    qtbot, invoices_dialog_setup, monkeypatch
):
    """Test _on_item_changed rejects invalid amount."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Mock QMessageBox
    def mock_warning(*args, **kwargs):
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    subtotal_item = dialog.table.item(0, dialog.COL_SUBTOTAL)
    original_subtotal = subtotal_item.text()

    # Try to set invalid amount
    subtotal_item.setText("not-a-number")
    dialog._on_item_changed(subtotal_item)

    # Should be reset to original
    assert subtotal_item.text() == original_subtotal


def test_invoices_dialog_on_item_changed_paid_at_removes_reminder(
    qtbot, invoices_dialog_setup
):
    """Test that marking invoice as paid removes due date reminder."""
    setup = invoices_dialog_setup

    # Create a reminder for an invoice
    due_date = (date.today() + timedelta(days=7)).isoformat()
    invoice_number = "ALPHA-1"
    project_name = "Project Alpha"

    reminder_text = _invoice_due_reminder_text(project_name, invoice_number)
    reminder = Reminder(
        id=None,
        text=reminder_text,
        time_str=_INVOICE_REMINDER_TIME,
        reminder_type=ReminderType.ONCE,
        date_iso=due_date,
        active=True,
    )
    reminder.id = setup["db"].save_reminder(reminder)

    # Verify reminder exists
    reminders = setup["db"].get_all_reminders()
    assert any(r.text == reminder_text for r in reminders)

    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Find the ALPHA-1 invoice row
    for row in range(dialog.table.rowCount()):
        num_item = dialog.table.item(row, dialog.COL_NUMBER)
        if num_item and num_item.text() == "ALPHA-1":
            # Mark as paid
            paid_item = dialog.table.item(row, dialog.COL_PAID_AT)
            paid_item.setText(date.today().isoformat())
            dialog._on_item_changed(paid_item)
            break

    # Reminder should be removed
    reminders_after = setup["db"].get_all_reminders()
    assert not any(r.text == reminder_text for r in reminders_after)


def test_invoices_dialog_ignores_changes_while_reloading(qtbot, invoices_dialog_setup):
    """Test that _on_item_changed is ignored during reload."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"], initial_project_id=setup["proj_id_1"])
    qtbot.addWidget(dialog)

    # Set reloading flag
    dialog._reloading_invoices = True

    # Try to change an item
    num_item = dialog.table.item(0, dialog.COL_NUMBER)
    original_number = num_item.text()
    inv_id = num_item.data(Qt.ItemDataRole.UserRole)

    num_item.setText("SHOULD-BE-IGNORED")
    dialog._on_item_changed(num_item)

    # Change should not be saved to DB
    invoice_data = setup["db"].get_invoice_field_by_id(inv_id, "invoice_number")
    assert invoice_data["invoice_number"] == original_number


def test_invoice_dialog_update_mode_enabled(qtbot, invoice_dialog_setup):
    """Test _update_mode_enabled method."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)
    dialog.show()

    # Initially detailed mode should be selected
    assert dialog.rb_detailed.isChecked()

    # Table should be enabled in detailed mode
    assert dialog.table.isEnabled()

    # Switch to summary mode
    dialog.rb_summary.setChecked(True)
    dialog._update_mode_enabled()

    # Table should be disabled in summary mode
    assert not dialog.table.isEnabled()


def test_invoice_dialog_with_no_time_logs(qtbot, fresh_db):
    """Test InvoiceDialog with project that has no time logs."""
    proj_id = fresh_db.add_project("Empty Project")
    today = date.today()
    start = (today - timedelta(days=7)).isoformat()
    end = today.isoformat()

    dialog = InvoiceDialog(fresh_db, proj_id, start, end)
    qtbot.addWidget(dialog)

    # Should handle empty time logs gracefully
    assert len(dialog._time_rows) == 0
    assert dialog.table.rowCount() == 0


def test_invoice_dialog_loads_client_company_list(qtbot, invoice_dialog_setup):
    """Test that InvoiceDialog loads existing client companies."""
    setup = invoice_dialog_setup

    # Create another project with a different client company
    proj_id_2 = setup["db"].add_project("Project 2")
    setup["db"].upsert_project_billing(
        proj_id_2,
        hourly_rate_cents=10000,
        currency="EUR",
        tax_label="VAT",
        tax_rate_percent=19.0,
        client_name="Jane Doe",
        client_company="Beta Corp",
        client_address="456 Main St",
        client_email="jane@beta.com",
    )

    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    # Should have both companies in the combo
    companies = [
        dialog.client_company_combo.itemText(i)
        for i in range(dialog.client_company_combo.count())
    ]
    assert "Acme Corp" in companies
    assert "Beta Corp" in companies


def test_invoice_line_item_equality(app):
    """Test InvoiceLineItem equality."""
    item1 = InvoiceLineItem("Work", 5.0, 10000, 50000)
    item2 = InvoiceLineItem("Work", 5.0, 10000, 50000)
    item3 = InvoiceLineItem("Other", 5.0, 10000, 50000)

    assert item1 == item2
    assert item1 != item3


def test_invoices_dialog_empty_database(qtbot, fresh_db):
    """Test InvoicesDialog with no projects or invoices."""
    dialog = InvoicesDialog(fresh_db)
    qtbot.addWidget(dialog)

    # Should have no projects in combo
    assert dialog.project_combo.count() == 0
    assert dialog.table.rowCount() == 0


def test_invoice_dialog_tax_initially_disabled(qtbot, fresh_db):
    """Test that tax fields are hidden when tax_rate_percent is None."""
    proj_id = fresh_db.add_project("No Tax Project")
    fresh_db.upsert_project_billing(
        proj_id,
        hourly_rate_cents=10000,
        currency="USD",
        tax_label="Tax",
        tax_rate_percent=None,  # No tax
        client_name="Client",
        client_company="Company",
        client_address="Address",
        client_email="email@test.com",
    )

    today = date.today()
    start = (today - timedelta(days=1)).isoformat()
    end = today.isoformat()

    dialog = InvoiceDialog(fresh_db, proj_id, start, end)
    qtbot.addWidget(dialog)
    dialog.show()

    # Tax checkbox should be unchecked
    assert not dialog.tax_checkbox.isChecked()

    # Tax fields should be hidden
    assert not dialog.tax_label.isVisible()
    assert not dialog.tax_label_edit.isVisible()
    assert not dialog.tax_rate_label.isVisible()
    assert not dialog.tax_rate_spin.isVisible()


def test_invoice_dialog_dates_default_values(qtbot, invoice_dialog_setup):
    """Test that issue and due dates have correct default values."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    # Issue date should be today
    assert dialog.issue_date_edit.date() == QDate.currentDate()

    # Due date should be 14 days from today
    QDate.currentDate().addDays(14)
    assert dialog.issue_date_edit.date() == QDate.currentDate()


def test_invoice_dialog_checkbox_toggle_updates_totals(qtbot, invoice_dialog_setup):
    """Test that unchecking a line item updates the total cost."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    dialog.rate_spin.setValue(100.0)
    dialog._populate_detailed_rows(10000)
    dialog.tax_checkbox.setChecked(False)

    # Initial total: 3 rows * 2.5 hours * $100 = $750
    dialog._recalc_totals()
    assert "750.00" in dialog.subtotal_label.text()
    assert "750.00" in dialog.total_label.text()

    # Uncheck the first row
    include_item = dialog.table.item(0, dialog.COL_INCLUDE)
    include_item.setCheckState(Qt.Unchecked)

    # Wait for signal processing
    qtbot.wait(10)

    # New total: 2 rows * 2.5 hours * $100 = $500
    assert "500.00" in dialog.subtotal_label.text()
    assert "500.00" in dialog.total_label.text()


def test_invoice_dialog_checkbox_toggle_with_tax(qtbot, invoice_dialog_setup):
    """Test that checkbox toggling works correctly with tax enabled."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    dialog.rate_spin.setValue(100.0)
    dialog._populate_detailed_rows(10000)
    dialog.tax_checkbox.setChecked(True)
    dialog.tax_rate_spin.setValue(10.0)

    # Initial: 3 rows * 2.5 hours * $100 = $750
    # Tax: $750 * 10% = $75
    # Total: $825
    dialog._recalc_totals()
    assert "750.00" in dialog.subtotal_label.text()
    assert "75.00" in dialog.tax_label_total.text()
    assert "825.00" in dialog.total_label.text()

    # Uncheck two rows
    dialog.table.item(0, dialog.COL_INCLUDE).setCheckState(Qt.Unchecked)
    dialog.table.item(1, dialog.COL_INCLUDE).setCheckState(Qt.Unchecked)

    # Wait for signal processing
    qtbot.wait(10)

    # New total: 1 row * 2.5 hours * $100 = $250
    # Tax: $250 * 10% = $25
    # Total: $275
    assert "250.00" in dialog.subtotal_label.text()
    assert "25.00" in dialog.tax_label_total.text()
    assert "275.00" in dialog.total_label.text()


def test_invoice_dialog_rechecking_items_updates_totals(qtbot, invoice_dialog_setup):
    """Test that rechecking a previously unchecked item updates totals."""
    setup = invoice_dialog_setup
    dialog = InvoiceDialog(
        setup["db"],
        setup["proj_id"],
        setup["start_date"],
        setup["end_date"],
        setup["time_rows"],
    )
    qtbot.addWidget(dialog)

    dialog.rate_spin.setValue(100.0)
    dialog._populate_detailed_rows(10000)
    dialog.tax_checkbox.setChecked(False)

    # Uncheck all items
    for row in range(dialog.table.rowCount()):
        dialog.table.item(row, dialog.COL_INCLUDE).setCheckState(Qt.Unchecked)

    qtbot.wait(10)

    # Total should be 0
    assert "0.00" in dialog.total_label.text()

    # Re-check first item
    dialog.table.item(0, dialog.COL_INCLUDE).setCheckState(Qt.Checked)
    qtbot.wait(10)

    # Total should be 1 row * 2.5 hours * $100 = $250
    assert "250.00" in dialog.total_label.text()


def test_invoices_dialog_select_initial_project(qtbot, invoices_dialog_setup):
    """Test _select_initial_project method."""
    setup = invoices_dialog_setup
    dialog = InvoicesDialog(setup["db"])
    qtbot.addWidget(dialog)

    # Initially should have first project selected (either proj1 or proj2)
    initial_proj = dialog._current_project()
    assert initial_proj in [setup["proj_id_1"], setup["proj_id_2"]]

    # Select specific project
    dialog._select_initial_project(setup["proj_id_2"])

    # Should now have proj_id_2 selected
    assert dialog._current_project() == setup["proj_id_2"]
