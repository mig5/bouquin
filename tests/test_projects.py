from unittest.mock import patch

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDialog, QMessageBox

from bouquin.projects import (
    ProjectsDialog,
    format_bucket_status,
    hours_from_minutes,
    minutes_from_hours,
)
from bouquin.time_log import TimeLogDialog, TimeReportDialog


def _add_project(fresh_db, project_name: str) -> int:
    project_id = fresh_db.add_project(project_name)
    fresh_db.upsert_project_billing(
        project_id,
        hourly_rate_cents=15000,
        currency="AUD",
        tax_label="GST",
        tax_rate_percent=10.0,
        client_name=f"{project_name} Contact",
        client_company=project_name,
        client_address="1 Example Street",
        client_email="client@example.test",
    )
    return project_id


def _add_minutes(fresh_db, project_id: int, minutes: int, note: str = "Work") -> int:
    activity_id = fresh_db.add_activity("Support")
    return fresh_db.add_time_log("2026-01-01", project_id, activity_id, minutes, note)


# ============================================================================
# Unit helpers
# ============================================================================


def test_project_hour_minute_helpers_round_trip():
    assert hours_from_minutes(None) == 0.0
    assert hours_from_minutes(90) == 1.5
    assert minutes_from_hours(None) == 0
    assert minutes_from_hours(1.25) == 75
    assert minutes_from_hours(1.333) == 80


def test_format_bucket_status_handles_none_unconfigured_and_reached(fresh_db):
    assert "Select a project" in format_bucket_status(None)

    project_id = _add_project(fresh_db, "No Bucket Project")
    _add_minutes(fresh_db, project_id, 30)
    unconfigured = fresh_db.project_bucket_status(project_id)
    text = format_bucket_status(unconfigured)
    assert "No Bucket Project" in text
    assert "No bucket ceiling" in text
    assert "0.50h used" in text

    fresh_db.upsert_project_bucket(project_id, 30, 60, 50.0)
    reached = fresh_db.project_bucket_status(project_id)
    text = format_bucket_status(reached)
    assert "1.00h / 1.00h" in text
    assert "Bucket ceiling reached" in text


# ============================================================================
# DB behaviour
# ============================================================================


def test_project_bucket_status_includes_baseline_and_logged_time(fresh_db):
    project_id = _add_project(fresh_db, "Support Retainer")
    _add_minutes(fresh_db, project_id, 90)
    fresh_db.upsert_project_bucket(
        project_id,
        baseline_minutes=60,
        bucket_ceiling_minutes=180,
        warn_at_percent=80.0,
    )

    status = fresh_db.project_bucket_status(project_id)
    assert status["project_id"] == project_id
    assert status["project_name"] == "Support Retainer"
    assert status["baseline_minutes"] == 60
    assert status["logged_minutes"] == 90
    assert status["used_minutes"] == 150
    assert status["remaining_minutes"] == 30
    assert status["percent_used"] == 150 / 180 * 100.0
    assert status["state"] == "warning"

    fresh_db.add_to_project_bucket_ceiling(project_id, 60)
    status = fresh_db.project_bucket_status(project_id)
    assert status["bucket_ceiling_minutes"] == 240
    assert status["state"] == "ok"


def test_project_bucket_status_state_boundaries(fresh_db):
    project_id = _add_project(fresh_db, "Boundary Project")

    _add_minutes(fresh_db, project_id, 30)
    status = fresh_db.project_bucket_status(project_id)
    assert status["state"] == "unconfigured"
    assert status["bucket_ceiling_minutes"] == 0
    assert status["remaining_minutes"] is None
    assert status["percent_used"] is None

    fresh_db.upsert_project_bucket(project_id, 0, 120, 80.0)
    assert fresh_db.project_bucket_status(project_id)["state"] == "ok"

    fresh_db.upsert_project_bucket(project_id, 66, 120, 80.0)
    status = fresh_db.project_bucket_status(project_id)
    assert status["used_minutes"] == 96
    assert status["percent_used"] == 80.0
    assert status["state"] == "warning"

    fresh_db.upsert_project_bucket(project_id, 90, 120, 80.0)
    status = fresh_db.project_bucket_status(project_id)
    assert status["used_minutes"] == 120
    assert status["remaining_minutes"] == 0
    assert status["state"] == "reached"

    fresh_db.upsert_project_bucket(project_id, 91, 120, 80.0)
    status = fresh_db.project_bucket_status(project_id)
    assert status["used_minutes"] == 121
    assert status["remaining_minutes"] == -1
    assert status["state"] == "exceeded"


def test_project_bucket_input_sanitisation_and_invalid_projects(fresh_db):
    project_id = _add_project(fresh_db, "Sanitised Project")
    fresh_db.upsert_project_bucket(
        project_id,
        baseline_minutes=-60,
        bucket_ceiling_minutes=-120,
        warn_at_percent=150.0,
    )
    bucket = fresh_db.get_project_bucket(project_id)
    assert bucket["project_id"] == project_id
    assert bucket["baseline_minutes"] == 0
    assert bucket["bucket_ceiling_minutes"] == 0
    assert bucket["warn_at_percent"] == 100.0

    fresh_db.upsert_project_bucket(project_id, 10, 60, -5.0)
    bucket = fresh_db.get_project_bucket(project_id)
    assert bucket["warn_at_percent"] == 0.0

    fresh_db.add_to_project_bucket_ceiling(project_id, -60)
    assert fresh_db.get_project_bucket(project_id)["bucket_ceiling_minutes"] == 60

    for bad_project_id in (0, -1):
        try:
            fresh_db.upsert_project_bucket(bad_project_id, 0, 60, 80.0)
        except ValueError as exc:
            assert "invalid project id" in str(exc)
        else:
            raise AssertionError("invalid project id should raise")

    assert fresh_db.get_project_bucket(0) is None
    assert fresh_db.logged_minutes_for_project(0) == 0
    assert fresh_db.project_bucket_status(0) is None
    assert fresh_db.time_logs_for_project(0) == []
    assert fresh_db.invoices_for_project_with_documents(0) == []


def test_project_summaries_include_all_projects_and_are_sorted(fresh_db):
    alpha = _add_project(fresh_db, "alpha project")
    zulu = _add_project(fresh_db, "Zulu Project")
    fresh_db.upsert_project_bucket(zulu, 15, 120, 80.0)

    rows = fresh_db.list_project_summaries()
    names = [r["project_name"] for r in rows]
    assert names == ["alpha project", "Zulu Project"]

    alpha_row = next(r for r in rows if r["project_id"] == alpha)
    assert alpha_row["document_count"] == 0
    assert alpha_row["invoice_count"] == 0
    assert alpha_row["time_log_count"] == 0
    assert alpha_row["logged_minutes"] == 0
    assert alpha_row["baseline_minutes"] == 0

    zulu_row = next(r for r in rows if r["project_id"] == zulu)
    assert zulu_row["baseline_minutes"] == 15
    assert zulu_row["bucket_ceiling_minutes"] == 120


def test_project_documents_time_logs_and_invoices_are_isolated(fresh_db, tmp_path):
    project_id = _add_project(fresh_db, "Project With Docs")
    other_project = _add_project(fresh_db, "Other Project")
    _add_minutes(fresh_db, project_id, 120, "Build work")
    _add_minutes(fresh_db, other_project, 300, "Other work")
    fresh_db.upsert_project_bucket(project_id, 0, 240, 80.0)

    doc_path = tmp_path / "invoice.pdf"
    doc_path.write_bytes(b"not really a pdf")
    doc_id = fresh_db.add_document_from_path(
        project_id,
        str(doc_path),
        description="Invoice document",
        uploaded_at="2026-02-02",
    )

    other_doc = tmp_path / "other.pdf"
    other_doc.write_bytes(b"other")
    fresh_db.add_document_from_path(other_project, str(other_doc))

    invoice_id = fresh_db.create_invoice(
        project_id=project_id,
        invoice_number="INV-1",
        issue_date="2026-02-03",
        due_date="2026-02-17",
        currency="AUD",
        tax_label=None,
        tax_rate_percent=None,
        detail_mode="summary",
        line_items=[("Prepaid bucket", 2.0, 10000)],
        time_log_ids=[],
    )
    fresh_db.set_invoice_document(invoice_id, doc_id)
    fresh_db.create_invoice(
        project_id=other_project,
        invoice_number="INV-OTHER",
        issue_date="2026-02-03",
        due_date="2026-02-17",
        currency="AUD",
        tax_label=None,
        tax_rate_percent=None,
        detail_mode="summary",
        line_items=[("Other", 1.0, 10000)],
        time_log_ids=[],
    )

    row = next(
        r for r in fresh_db.list_project_summaries() if r["project_id"] == project_id
    )
    assert row["logged_minutes"] == 120
    assert row["time_log_count"] == 1
    assert row["document_count"] == 1
    assert row["invoice_count"] == 1

    logs = fresh_db.time_logs_for_project(project_id)
    assert len(logs) == 1
    assert logs[0]["note"] == "Build work"

    docs = fresh_db.documents_for_project(project_id)
    assert len(docs) == 1
    assert docs[0][3] == "invoice.pdf"

    invoices = fresh_db.invoices_for_project_with_documents(project_id)
    assert len(invoices) == 1
    assert invoices[0]["invoice_number"] == "INV-1"
    assert invoices[0]["document_id"] == doc_id
    assert invoices[0]["document_file_name"] == "invoice.pdf"


def test_prepaid_invoice_can_exist_without_logged_time_links(fresh_db):
    project_id = _add_project(fresh_db, "Prepaid Project")

    invoice_id = fresh_db.create_invoice(
        project_id=project_id,
        invoice_number="PREPAID-1",
        issue_date="2026-02-10",
        due_date="2026-02-24",
        currency="AUD",
        tax_label=None,
        tax_rate_percent=None,
        detail_mode="summary",
        line_items=[("Prepaid support bucket", 40.0, 15000)],
        time_log_ids=[],
    )

    invoice = fresh_db.invoices_for_project_with_documents(project_id)[0]
    assert invoice["id"] == invoice_id
    assert invoice["total_cents"] == 600000

    linked = fresh_db.conn.execute(
        "SELECT COUNT(*) AS c FROM invoice_time_log WHERE invoice_id = ?",
        (invoice_id,),
    ).fetchone()
    assert linked["c"] == 0


# ============================================================================
# UI behaviour
# ============================================================================


def test_projects_dialog_loads_summary_time_logs_documents_and_invoices(
    qtbot, fresh_db, tmp_path
):
    project_id = _add_project(fresh_db, "UI Project")
    _add_minutes(fresh_db, project_id, 60, "Initial support")
    fresh_db.upsert_project_bucket(project_id, 30, 120, 75.0)

    doc_path = tmp_path / "ui-invoice.pdf"
    doc_path.write_bytes(b"ui")
    doc_id = fresh_db.add_document_from_path(
        project_id,
        str(doc_path),
        description="UI invoice",
        uploaded_at="2026-03-01",
    )
    invoice_id = fresh_db.create_invoice(
        project_id,
        "UI-1",
        "2026-03-02",
        "2026-03-16",
        "AUD",
        None,
        None,
        "summary",
        [("UI work", 1.0, 10000)],
        [],
    )
    fresh_db.set_invoice_document(invoice_id, doc_id)

    dialog = ProjectsDialog(fresh_db)
    qtbot.addWidget(dialog)

    assert dialog.project_combo.currentData() == project_id
    assert dialog.summary_table.rowCount() == 1
    assert dialog.time_logs_table.rowCount() == 1
    assert dialog.documents_table.rowCount() == 1
    assert dialog.invoices_table.rowCount() == 1
    assert dialog.summary_table.item(0, dialog.SUM_USED).text() == "1.50"
    assert (
        dialog.summary_table.item(0, dialog.SUM_STATE).text()
        == "Approaching bucket ceiling"
    )
    assert dialog.time_logs_table.item(0, dialog.LOG_NOTE).text() == "Initial support"
    assert dialog.documents_table.item(0, dialog.DOC_FILE).text() == "ui-invoice.pdf"
    assert dialog.invoices_table.item(0, dialog.INV_NUMBER).text() == "UI-1"
    assert "UI Project" in dialog.status_label.text()
    assert "1.50h / 2.00h" in dialog.status_label.text()
    assert (
        dialog.status_label.minimumHeight()
        >= dialog.status_label.fontMetrics().lineSpacing() * 3 + 18
    )


def test_projects_dialog_saves_and_replenishes_bucket(qtbot, fresh_db):
    project_id = _add_project(fresh_db, "Editable Project")

    dialog = ProjectsDialog(fresh_db)
    qtbot.addWidget(dialog)
    assert dialog.project_combo.currentData() == project_id

    dialog.baseline_spin.setValue(1.5)
    dialog.ceiling_spin.setValue(10.0)
    dialog.warn_spin.setValue(75.0)
    dialog._save_bucket()

    bucket = fresh_db.get_project_bucket(project_id)
    assert bucket["baseline_minutes"] == 90
    assert bucket["bucket_ceiling_minutes"] == 600
    assert bucket["warn_at_percent"] == 75.0

    dialog.topup_spin.setValue(40.0)
    dialog._add_to_ceiling()

    bucket = fresh_db.get_project_bucket(project_id)
    assert bucket["bucket_ceiling_minutes"] == 3000
    assert "48.50h remaining" in dialog.status_label.text()


class _FakeRadioButton:
    def __init__(self):
        self.checked = False

    def setChecked(self, checked):
        self.checked = checked


class _FakeLineEdit:
    def __init__(self):
        self.value = ""

    def setText(self, text):
        self.value = text


class _FakeSpinBox:
    def __init__(self):
        self.value_set = None

    def setValue(self, value):
        self.value_set = value


class _FakeInvoiceDialog:
    instances = []

    def __init__(
        self, db, project_id, start_date_iso, end_date_iso, time_rows=None, parent=None
    ):
        self.db = db
        self.project_id = project_id
        self.start_date_iso = start_date_iso
        self.end_date_iso = end_date_iso
        self.time_rows = time_rows
        self.parent = parent
        self.rb_summary = _FakeRadioButton()
        self.summary_desc_edit = _FakeLineEdit()
        self.summary_hours_spin = _FakeSpinBox()
        self.recalculated = False
        self.executed = False
        _FakeInvoiceDialog.instances.append(self)

    def _recalc_totals(self):
        self.recalculated = True

    def exec(self):
        self.executed = True
        return QDialog.Accepted


def test_projects_dialog_can_open_prepaid_invoice_for_unspent_hours(qtbot, fresh_db):
    project_id = _add_project(fresh_db, "Prepaid UI Project")
    dialog = ProjectsDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.topup_spin.setValue(40.0)

    _FakeInvoiceDialog.instances.clear()
    with patch("bouquin.projects.InvoiceDialog", _FakeInvoiceDialog):
        dialog._invoice_prepaid_hours()

    assert len(_FakeInvoiceDialog.instances) == 1
    invoice_dialog = _FakeInvoiceDialog.instances[0]
    assert invoice_dialog.db is fresh_db
    assert invoice_dialog.project_id == project_id
    assert invoice_dialog.time_rows == []
    assert invoice_dialog.parent is dialog
    assert invoice_dialog.rb_summary.checked is True
    assert invoice_dialog.summary_hours_spin.value_set == 40.0
    assert invoice_dialog.summary_desc_edit.value == (
        "Prepaid support bucket (40.00 hours)"
    )
    assert invoice_dialog.recalculated is True
    assert invoice_dialog.executed is True


def test_projects_dialog_warns_when_prepaid_invoice_hours_are_zero(qtbot, fresh_db):
    _add_project(fresh_db, "Zero Project")
    dialog = ProjectsDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.topup_spin.setValue(0.0)

    with patch.object(QMessageBox, "warning") as warning:
        dialog._invoice_prepaid_hours()

    assert warning.called
    assert "greater than zero" in warning.call_args.args[2]


def test_projects_dialog_opens_selected_document_and_invoice_document(
    qtbot, fresh_db, tmp_path
):
    project_id = _add_project(fresh_db, "Open Project")
    doc_path = tmp_path / "open.pdf"
    doc_path.write_bytes(b"open")
    doc_id = fresh_db.add_document_from_path(project_id, str(doc_path))
    invoice_id = fresh_db.create_invoice(
        project_id,
        "OPEN-1",
        "2026-05-01",
        None,
        "AUD",
        None,
        None,
        "summary",
        [("Open work", 1.0, 10000)],
        [],
    )
    fresh_db.set_invoice_document(invoice_id, doc_id)

    dialog = ProjectsDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.documents_table.selectRow(0)
    with patch("bouquin.projects.open_document_from_db") as open_doc:
        dialog._open_selected_document()
        open_doc.assert_called_once_with(
            fresh_db, doc_id, "open.pdf", parent_widget=dialog
        )

    dialog.invoices_table.selectRow(0)
    with patch("bouquin.projects.open_document_from_db") as open_doc:
        dialog._open_invoice_document()
        open_doc.assert_called_once_with(
            fresh_db, doc_id, "open.pdf", parent_widget=dialog
        )


def test_projects_dialog_reports_missing_invoice_document(qtbot, fresh_db):
    project_id = _add_project(fresh_db, "No Doc Project")
    fresh_db.create_invoice(
        project_id,
        "NO-DOC-1",
        "2026-05-01",
        None,
        "AUD",
        None,
        None,
        "summary",
        [("Work", 1.0, 10000)],
        [],
    )

    dialog = ProjectsDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.invoices_table.selectRow(0)

    with patch.object(QMessageBox, "information") as info:
        dialog._open_invoice_document()
        assert info.called


def test_time_log_dialog_updates_bucket_indicator_and_alerts_on_reach(qtbot, fresh_db):
    project_id = _add_project(fresh_db, "Logging Project")
    fresh_db.upsert_project_bucket(project_id, 0, 60, 80.0)

    dialog = TimeLogDialog(fresh_db, "2026-06-01")
    qtbot.addWidget(dialog)

    idx = dialog.project_combo.findData(project_id)
    dialog.project_combo.setCurrentIndex(idx)
    assert "0.00h / 1.00h" in dialog.bucket_label.text()
    assert "Status: OK" in dialog.bucket_label.text()

    dialog.activity_edit.setText("Support")
    dialog.hours_spin.setValue(1.0)

    with patch.object(QMessageBox, "warning") as warning:
        dialog._on_add_or_update()
        assert warning.called
        assert "Bucket ceiling reached" in warning.call_args.args[2]

    status = fresh_db.project_bucket_status(project_id)
    assert status["state"] == "reached"
    assert "Bucket ceiling reached" in dialog.bucket_label.text()


def test_time_log_dialog_does_not_alert_before_reaching_bucket(qtbot, fresh_db):
    project_id = _add_project(fresh_db, "Safe Logging")
    fresh_db.upsert_project_bucket(project_id, 0, 120, 80.0)

    dialog = TimeLogDialog(fresh_db, "2026-06-02")
    qtbot.addWidget(dialog)
    dialog.project_combo.setCurrentIndex(dialog.project_combo.findData(project_id))
    dialog.activity_edit.setText("Support")
    dialog.hours_spin.setValue(0.5)

    with patch.object(QMessageBox, "warning") as warning:
        dialog._on_add_or_update()
        warning.assert_not_called()

    assert fresh_db.project_bucket_status(project_id)["state"] == "ok"


def test_time_report_dialog_shows_bucket_for_selected_project_and_clears_for_all(
    qtbot, fresh_db
):
    project_id = _add_project(fresh_db, "Report Project")
    _add_minutes(fresh_db, project_id, 90)
    fresh_db.upsert_project_bucket(project_id, 0, 120, 75.0)

    dialog = TimeReportDialog(fresh_db)
    qtbot.addWidget(dialog)

    dialog.from_date.setDate(QDate.fromString("2026-01-01", "yyyy-MM-dd"))
    dialog.to_date.setDate(QDate.fromString("2026-01-31", "yyyy-MM-dd"))

    dialog.project_combo.setCurrentIndex(dialog.project_combo.findData(project_id))
    dialog._run_report()
    assert "Report Project" in dialog.bucket_label.text()
    assert "Approaching bucket ceiling" in dialog.bucket_label.text()

    dialog.project_combo.setCurrentIndex(dialog.project_combo.findData(None))
    dialog._run_report()
    assert dialog.bucket_label.text() == ""


def test_project_bucket_ledger_records_settings_topups_and_time_use(fresh_db):
    project_id = _add_project(fresh_db, "Ledger Project")

    fresh_db.upsert_project_bucket(project_id, 30, 120, 80.0)
    fresh_db.add_to_project_bucket_ceiling(
        project_id,
        60,
        description="Extra prepaid hours",
    )
    _add_minutes(fresh_db, project_id, 45, "Ledger work")

    rows = fresh_db.project_bucket_ledger_for_project(project_id)
    types = [r["entry_type"] for r in rows]
    assert "settings_adjustment" in types
    assert "manual_topup" in types
    assert "time_log" in types

    settings = next(r for r in rows if r["entry_type"] == "settings_adjustment")
    assert settings["baseline_delta_minutes"] == 30
    assert settings["ceiling_delta_minutes"] == 120

    topup = next(r for r in rows if r["entry_type"] == "manual_topup")
    assert topup["ceiling_delta_minutes"] == 60
    assert topup["description"] == "Extra prepaid hours"

    time_log = next(r for r in rows if r["entry_type"] == "time_log")
    assert time_log["used_delta_minutes"] == 45
    assert time_log["description"] == "Ledger work"

    status = fresh_db.project_bucket_status(project_id)
    assert status["baseline_minutes"] == 30
    assert status["logged_minutes"] == 45
    assert status["bucket_ceiling_minutes"] == 180
    assert status["remaining_minutes"] == 105


def test_project_bucket_ledger_records_negative_corrections(fresh_db):
    project_id = _add_project(fresh_db, "Correction Project")

    fresh_db.upsert_project_bucket(project_id, 120, 240, 80.0)
    fresh_db.upsert_project_bucket(project_id, 60, 180, 80.0)

    rows = [
        r
        for r in fresh_db.project_bucket_ledger_for_project(project_id)
        if r["entry_type"] == "settings_adjustment"
    ]
    assert len(rows) == 2
    assert any(r["baseline_delta_minutes"] == -60 for r in rows)
    assert any(r["ceiling_delta_minutes"] == -60 for r in rows)

    status = fresh_db.project_bucket_status(project_id)
    assert status["baseline_minutes"] == 60
    assert status["bucket_ceiling_minutes"] == 180


def test_project_activity_log_includes_time_documents_invoices_and_bucket_events(
    fresh_db, tmp_path
):
    project_id = _add_project(fresh_db, "Activity Log Project")
    _add_minutes(fresh_db, project_id, 30, "Log work")
    fresh_db.upsert_project_bucket(project_id, 0, 120, 80.0)

    doc_path = tmp_path / "activity-doc.pdf"
    doc_path.write_bytes(b"activity")
    fresh_db.add_document_from_path(
        project_id,
        str(doc_path),
        description="Activity document",
        uploaded_at="2026-04-01",
    )
    fresh_db.create_invoice(
        project_id=project_id,
        invoice_number="ACT-001",
        issue_date="2026-04-02",
        due_date="2026-04-16",
        currency="AUD",
        tax_label=None,
        tax_rate_percent=None,
        detail_mode="summary",
        line_items=[("Activity prepaid", 2.0, 10000)],
        time_log_ids=[],
    )

    rows = fresh_db.project_activity_log_for_project(project_id)
    event_types = [r["event_type"] for r in rows]
    assert "time_log" in event_types
    assert "document" in event_types
    assert "invoice" in event_types
    assert "bucket" in event_types
    assert any("Log work" in r["details"] for r in rows)
    assert any("activity-doc.pdf" in r["details"] for r in rows)
    assert any("ACT-001" in r["details"] for r in rows)
    assert any("Bucket settings updated" in r["details"] for r in rows)


def test_projects_dialog_shows_bucket_ledger_and_project_log(qtbot, fresh_db, tmp_path):
    project_id = _add_project(fresh_db, "Ledger UI Project")
    _add_minutes(fresh_db, project_id, 60, "UI ledger work")
    fresh_db.upsert_project_bucket(project_id, 30, 120, 75.0)
    fresh_db.add_to_project_bucket_ceiling(
        project_id,
        60,
        description="UI top-up",
    )

    doc_path = tmp_path / "ledger-ui.pdf"
    doc_path.write_bytes(b"ledger")
    fresh_db.add_document_from_path(project_id, str(doc_path), uploaded_at="2026-05-01")
    fresh_db.create_invoice(
        project_id=project_id,
        invoice_number="LEDGER-UI-001",
        issue_date="2026-05-02",
        due_date=None,
        currency="AUD",
        tax_label=None,
        tax_rate_percent=None,
        detail_mode="summary",
        line_items=[("Ledger UI prepaid", 1.0, 10000)],
        time_log_ids=[],
    )

    dialog = ProjectsDialog(fresh_db)
    qtbot.addWidget(dialog)

    assert dialog.bucket_ledger_table.rowCount() == 3
    ledger_types = {
        dialog.bucket_ledger_table.item(row, dialog.LEDGER_TYPE).text()
        for row in range(dialog.bucket_ledger_table.rowCount())
    }
    assert "Bucket settings" in ledger_types
    assert "Manual top-up" in ledger_types
    assert "Time logged" in ledger_types
    assert any(
        dialog.bucket_ledger_table.item(row, dialog.LEDGER_NOTE).text()
        for row in range(dialog.bucket_ledger_table.rowCount())
    )

    changelog_types = {
        dialog.changelog_table.item(row, dialog.CHANGE_TYPE).text()
        for row in range(dialog.changelog_table.rowCount())
    }
    assert {"Time log", "Document", "Invoice", "Bucket"}.issubset(changelog_types)
    assert any(
        "LEDGER-UI-001"
        in dialog.changelog_table.item(row, dialog.CHANGE_DETAILS).text()
        for row in range(dialog.changelog_table.rowCount())
    )


def test_prepaid_invoice_dialog_adds_bucket_ledger_entry_when_invoice_is_created(
    qtbot, fresh_db
):
    project_id = _add_project(fresh_db, "Prepaid Ledger Project")
    invoice_id = fresh_db.create_invoice(
        project_id=project_id,
        invoice_number="PREPAID-LEDGER-001",
        issue_date="2026-06-01",
        due_date=None,
        currency="AUD",
        tax_label=None,
        tax_rate_percent=None,
        detail_mode="summary",
        line_items=[("Prepaid", 40.0, 15000)],
        time_log_ids=[],
    )
    dialog = ProjectsDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.topup_spin.setValue(40.0)

    class _InvoiceDialogWithId(_FakeInvoiceDialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.last_invoice_id = invoice_id

    with patch("bouquin.projects.InvoiceDialog", _InvoiceDialogWithId):
        dialog._invoice_prepaid_hours()

    row = next(
        r
        for r in fresh_db.project_bucket_ledger_for_project(project_id)
        if r["entry_type"] == "prepaid_invoice"
    )
    assert row["ceiling_delta_minutes"] == 2400
    assert row["invoice_id"] == invoice_id
    assert "40.00 hours" in row["description"]
