from bouquin.earnings import (
    aggregate_invoices_by_month,
    aggregate_payments_by_month,
    invoice_reporting_amount_cents,
)


def _invoice(
    db,
    project_id,
    number,
    currency="AUD",
    tax_rate=10.0,
    issue_date="2026-04-01",
):
    return db.create_invoice(
        project_id=project_id,
        invoice_number=number,
        issue_date=issue_date,
        due_date=issue_date,
        currency=currency,
        tax_label="GST" if tax_rate else None,
        tax_rate_percent=tax_rate,
        detail_mode="summary",
        line_items=[("Consulting", 10.0, 1000)],
        time_log_ids=[],
    )


def test_partial_payments_mark_invoice_paid_only_when_fully_settled(fresh_db):
    project_id = fresh_db.add_project("Client A")
    invoice_id = _invoice(fresh_db, project_id, "INV-1")

    first = fresh_db.add_invoice_payment(
        invoice_id,
        received_at="2026-04-15",
        invoice_amount_cents=5500,
        reporting_currency="AUD",
        reporting_amount_cents=5500,
        note="First half",
    )
    assert first > 0
    assert fresh_db.get_invoice_with_project(invoice_id)["paid_at"] is None

    second = fresh_db.add_invoice_payment(
        invoice_id,
        received_at="2026-05-03",
        invoice_amount_cents=5500,
        reporting_currency="AUD",
        reporting_amount_cents=5500,
        note="Balance",
    )
    assert second > first
    assert fresh_db.get_invoice_with_project(invoice_id)["paid_at"] == "2026-05-03"

    fresh_db.delete_invoice_payment(second)
    assert fresh_db.get_invoice_with_project(invoice_id)["paid_at"] is None


def test_invoice_basis_uses_invoice_date_value_not_later_bank_receipt(fresh_db):
    project_id = fresh_db.add_project("Foreign Client")
    invoice_id = _invoice(fresh_db, project_id, "USD-1", currency="USD")

    # Value of the invoice in AUD on the invoice-date conversion basis.
    fresh_db.set_invoice_reporting_value(
        invoice_id,
        reporting_currency="AUD",
        reporting_total_cents=16500,
        note="Invoice-date FX rate",
    )

    # The eventual bank receipt is later and a different AUD amount.
    fresh_db.add_invoice_payment(
        invoice_id,
        received_at="2026-05-20",
        invoice_amount_cents=11000,
        reporting_currency="AUD",
        reporting_amount_cents=17000,
        note="Actual receipt",
    )

    invoice_rows = fresh_db.get_invoices_for_earnings_range("2026-04-01", "2026-06-30")
    monthly = aggregate_invoices_by_month(
        invoice_rows, "AUD", "2026-04-01", "2026-06-30"
    )

    assert monthly[0].month == "2026-04"
    assert monthly[0].sales_inc_tax_cents == 16500
    assert monthly[0].tax_cents == 1500
    assert monthly[0].sales_ex_tax_cents == 15000
    assert monthly[0].entry_count == 1
    assert monthly[1].sales_inc_tax_cents == 0

    payment_rows = fresh_db.get_payments_for_range("2026-04-01", "2026-06-30")
    payment_monthly = aggregate_payments_by_month(
        payment_rows, "2026-04-01", "2026-06-30"
    )
    assert payment_monthly[0].sales_inc_tax_cents == 0
    assert payment_monthly[1].sales_inc_tax_cents == 17000


def test_same_currency_invoice_needs_no_manual_reporting_value(fresh_db):
    project_id = fresh_db.add_project("Local Client")
    _invoice(fresh_db, project_id, "AUD-1", currency="AUD")

    rows = fresh_db.get_invoices_for_earnings_range("2026-04-01", "2026-04-30")
    assert len(rows) == 1
    assert rows[0]["reporting_total_cents"] is None
    assert invoice_reporting_amount_cents(rows[0], "AUD") == 11000

    monthly = aggregate_invoices_by_month(rows, "AUD", "2026-04-01", "2026-04-30")
    assert monthly[0].sales_inc_tax_cents == 11000
    assert monthly[0].tax_cents == 1000


def test_invoices_are_aggregated_by_issue_month(fresh_db):
    project_id = fresh_db.add_project("Client B")
    _invoice(
        fresh_db,
        project_id,
        "INV-APR",
        tax_rate=None,
        issue_date="2026-04-30",
    )
    _invoice(
        fresh_db,
        project_id,
        "INV-JUN",
        tax_rate=None,
        issue_date="2026-06-01",
    )

    rows = fresh_db.get_invoices_for_earnings_range("2026-04-01", "2026-06-30")
    monthly = aggregate_invoices_by_month(rows, "AUD", "2026-04-01", "2026-06-30")

    assert [r.sales_inc_tax_cents for r in monthly] == [10000, 0, 10000]
    assert [r.entry_count for r in monthly] == [1, 0, 1]


def test_foreign_invoice_without_reporting_value_is_not_guessed(fresh_db):
    project_id = fresh_db.add_project("Foreign Client")
    _invoice(fresh_db, project_id, "USD-MISSING", currency="USD")

    rows = fresh_db.get_invoices_for_earnings_range("2026-04-01", "2026-04-30")
    assert invoice_reporting_amount_cents(rows[0], "AUD") is None

    monthly = aggregate_invoices_by_month(rows, "AUD", "2026-04-01", "2026-04-30")
    assert monthly[0].sales_inc_tax_cents == 0
    assert monthly[0].entry_count == 0


def test_reporting_value_is_invalidated_when_invoice_date_changes(fresh_db):
    project_id = fresh_db.add_project("Foreign Client")
    invoice_id = _invoice(fresh_db, project_id, "USD-EDIT", currency="USD")
    fresh_db.set_invoice_reporting_value(invoice_id, "AUD", 16500, "RBA")

    fresh_db.set_invoice_field_by_id(invoice_id, "issue_date", "2026-04-02")
    invoice = fresh_db.get_invoice_with_project(invoice_id)
    assert invoice["reporting_currency"] is None
    assert invoice["reporting_total_cents"] is None
    assert invoice["reporting_note"] is None


def test_legacy_paid_invoice_is_reported_as_unstructured_for_payment_basis(fresh_db):
    project_id = fresh_db.add_project("Legacy Client")
    invoice_id = _invoice(fresh_db, project_id, "LEGACY-1")
    fresh_db.set_invoice_field_by_id(invoice_id, "paid_at", "2026-04-22")
    fresh_db.set_invoice_field_by_id(invoice_id, "payment_note", "Received AUD 110.00")

    missing = fresh_db.get_paid_invoices_without_payments("2026-04-01", "2026-06-30")

    assert len(missing) == 1
    assert missing[0]["invoice_number"] == "LEGACY-1"
