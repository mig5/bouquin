from __future__ import annotations

import csv
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import strings
from .db import DBManager
from .settings import load_db_config


@dataclass(frozen=True)
class MonthlyEarnings:
    month: str
    sales_ex_tax_cents: int = 0
    tax_cents: int = 0
    sales_inc_tax_cents: int = 0
    entry_count: int = 0


def _month_key(date_iso: str) -> str:
    return date_iso[:7]


def _iter_months(start_iso: str, end_iso: str):
    start = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield f"{year:04d}-{month:02d}"
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1


def aggregate_payments_by_month(rows, start_iso: str, end_iso: str):
    """Aggregate structured payment rows into reporting-currency monthly totals.

    Each invoice currently has a single invoice-wide tax rate, so a part-payment's
    tax component is the same proportion of the reporting-currency receipt as the
    invoice tax is of the invoice total.
    """
    totals = OrderedDict(
        (month, [0, 0, 0, 0]) for month in _iter_months(start_iso, end_iso)
    )

    for row in rows:
        gross = int(row["reporting_amount_cents"] or 0)
        invoice_total = int(row["total_cents"] or 0)
        invoice_tax = int(row["tax_cents"] or 0)
        tax = int(round(gross * invoice_tax / invoice_total)) if invoice_total else 0
        net = gross - tax
        bucket = totals.setdefault(_month_key(row["received_at"]), [0, 0, 0, 0])
        bucket[0] += net
        bucket[1] += tax
        bucket[2] += gross
        bucket[3] += 1

    return [
        MonthlyEarnings(
            month=month,
            sales_ex_tax_cents=values[0],
            tax_cents=values[1],
            sales_inc_tax_cents=values[2],
            entry_count=values[3],
        )
        for month, values in totals.items()
    ]


def invoice_reporting_amount_cents(row, reporting_currency: str) -> int | None:
    """Return an invoice's gross value in the requested reporting currency.

    Same-currency invoices are exact and need no extra valuation. Foreign-currency
    invoices require an explicit invoice-date reporting value so a later bank
    receipt is never silently reused as the tax/reporting value.
    """
    currency = str(row["currency"] or "").strip().upper()
    requested = reporting_currency.strip().upper()
    if currency == requested:
        return int(row["total_cents"] or 0)

    stored_currency = str(row["reporting_currency"] or "").strip().upper()
    stored_total = row["reporting_total_cents"]
    if stored_currency == requested and stored_total is not None:
        return int(stored_total)
    return None


def aggregate_invoices_by_month(
    rows, reporting_currency: str, start_iso: str, end_iso: str
):
    """Aggregate invoices by issue month in one reporting currency."""
    totals = OrderedDict(
        (month, [0, 0, 0, 0]) for month in _iter_months(start_iso, end_iso)
    )

    for row in rows:
        gross = invoice_reporting_amount_cents(row, reporting_currency)
        if gross is None:
            continue
        invoice_total = int(row["total_cents"] or 0)
        invoice_tax = int(row["tax_cents"] or 0)
        tax = int(round(gross * invoice_tax / invoice_total)) if invoice_total else 0
        net = gross - tax
        bucket = totals.setdefault(_month_key(row["issue_date"]), [0, 0, 0, 0])
        bucket[0] += net
        bucket[1] += tax
        bucket[2] += gross
        bucket[3] += 1

    return [
        MonthlyEarnings(
            month=month,
            sales_ex_tax_cents=values[0],
            tax_cents=values[1],
            sales_inc_tax_cents=values[2],
            entry_count=values[3],
        )
        for month, values in totals.items()
    ]


class InvoiceReportingValueDialog(QDialog):
    """Record the invoice-date value of a foreign-currency invoice."""

    valueChanged = Signal()

    def __init__(self, db: DBManager, invoice_id: int, parent=None):
        super().__init__(parent)
        self._db = db
        self._invoice_id = int(invoice_id)
        self.cfg = load_db_config()
        self._invoice = self._db.get_invoice_with_project(self._invoice_id)
        if self._invoice is None:
            raise ValueError(f"Invoice {invoice_id} does not exist")

        self.setWindowTitle(
            strings._("invoice_reporting_value_title").format(
                invoice=self._invoice["invoice_number"] or "?",
                project=self._invoice["project_name"] or "",
            )
        )
        self.resize(600, 330)
        root = QVBoxLayout(self)

        summary = QLabel(
            strings._("invoice_reporting_value_summary").format(
                issue_date=self._invoice["issue_date"] or "",
                total=int(self._invoice["total_cents"] or 0) / 100.0,
                currency=self._invoice["currency"] or "",
            )
        )
        summary.setWordWrap(True)
        root.addWidget(summary)

        form = QFormLayout()
        self.reporting_currency = QLineEdit(
            self._invoice["reporting_currency"] or self.cfg.reporting_currency or "AUD"
        )
        self.reporting_currency.setMaxLength(8)
        form.addRow(strings._("reporting_currency") + ":", self.reporting_currency)

        self.reporting_total = QDoubleSpinBox()
        self.reporting_total.setDecimals(2)
        self.reporting_total.setMaximum(999999999.99)
        if self._invoice["reporting_total_cents"] is not None:
            self.reporting_total.setValue(
                int(self._invoice["reporting_total_cents"]) / 100.0
            )
        elif (
            str(self._invoice["currency"] or "").upper()
            == str(self.reporting_currency.text() or "").upper()
        ):
            self.reporting_total.setValue(
                int(self._invoice["total_cents"] or 0) / 100.0
            )
        form.addRow(strings._("invoice_reporting_total") + ":", self.reporting_total)

        self.note = QTextEdit()
        self.note.setMaximumHeight(90)
        self.note.setPlainText(self._invoice["reporting_note"] or "")
        form.addRow(strings._("invoice_reporting_note") + ":", self.note)
        root.addLayout(form)

        help_label = QLabel(strings._("invoice_reporting_value_help"))
        help_label.setWordWrap(True)
        root.addWidget(help_label)

        buttons = QHBoxLayout()
        clear_btn = QPushButton(strings._("invoice_reporting_value_clear"))
        clear_btn.clicked.connect(self._clear)
        buttons.addWidget(clear_btn)
        buttons.addStretch(1)
        save_btn = QPushButton(strings._("save"))
        save_btn.clicked.connect(self._save)
        buttons.addWidget(save_btn)
        close_btn = QPushButton(strings._("close"))
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    def _save(self) -> None:
        currency = self.reporting_currency.text().strip().upper()
        amount_cents = int(round(self.reporting_total.value() * 100))
        if not currency or amount_cents <= 0:
            QMessageBox.warning(
                self, strings._("error"), strings._("invoice_reporting_value_required")
            )
            return
        self._db.set_invoice_reporting_value(
            self._invoice_id,
            currency,
            amount_cents,
            self.note.toPlainText(),
        )
        self.reporting_currency.setText(currency)
        self.valueChanged.emit()
        self.accept()

    def _clear(self) -> None:
        self._db.clear_invoice_reporting_value(self._invoice_id)
        self.valueChanged.emit()
        self.accept()


class EarningsChart(QWidget):
    """Small stacked monthly sales chart: ex-tax sales plus tax."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[MonthlyEarnings] = []
        self.setMinimumHeight(190)

    def set_rows(self, rows: list[MonthlyEarnings]) -> None:
        self._rows = rows
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt API
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())

        if not self._rows:
            painter.setPen(palette.text().color())
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, strings._("earnings_no_data")
            )
            return

        left, top, right, bottom = 56, 12, 16, 36
        plot_w = max(1, self.width() - left - right)
        plot_h = max(1, self.height() - top - bottom)
        max_gross = max((r.sales_inc_tax_cents for r in self._rows), default=0)
        if max_gross <= 0:
            painter.setPen(palette.text().color())
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, strings._("earnings_no_data")
            )
            return

        axis_pen = QPen(palette.mid().color())
        painter.setPen(axis_pen)
        painter.drawLine(left, top, left, top + plot_h)
        painter.drawLine(left, top + plot_h, left + plot_w, top + plot_h)

        count = max(1, len(self._rows))
        slot = plot_w / count
        bar_w = max(8.0, min(54.0, slot * 0.58))
        net_color = palette.highlight().color()
        tax_color = palette.mid().color()

        for idx, row in enumerate(self._rows):
            x = left + slot * idx + (slot - bar_w) / 2
            gross_h = (row.sales_inc_tax_cents / max_gross) * plot_h
            tax_h = (row.tax_cents / max_gross) * plot_h
            net_h = max(0.0, gross_h - tax_h)
            base_y = top + plot_h

            painter.fillRect(QRectF(x, base_y - net_h, bar_w, net_h), net_color)
            if tax_h > 0:
                painter.fillRect(QRectF(x, base_y - gross_h, bar_w, tax_h), tax_color)

            painter.setPen(palette.text().color())
            label = row.month[5:7] + "/" + row.month[2:4]
            painter.drawText(
                QRectF(left + slot * idx, base_y + 4, slot, 24),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                label,
            )

        painter.setPen(palette.text().color())
        painter.drawText(4, top + 12, f"{max_gross / 100.0:,.0f}")
        painter.drawText(4, top + plot_h, "0")


class PaymentsDialog(QDialog):
    """Record and manage structured receipts for one invoice."""

    paymentsChanged = Signal()

    COL_DATE = 0
    COL_INVOICE_AMOUNT = 1
    COL_REPORTING_AMOUNT = 2
    COL_RATE = 3
    COL_NOTE = 4

    def __init__(self, db: DBManager, invoice_id: int, parent=None):
        super().__init__(parent)
        self._db = db
        self._invoice_id = int(invoice_id)
        self.cfg = load_db_config()
        self._invoice = self._db.get_invoice_with_project(self._invoice_id)
        if self._invoice is None:
            raise ValueError(f"Invoice {invoice_id} does not exist")

        title = strings._("invoice_payments_title").format(
            invoice=self._invoice["invoice_number"] or "?",
            project=self._invoice["project_name"] or "",
        )
        self.setWindowTitle(title)
        self.resize(820, 520)

        root = QVBoxLayout(self)
        summary = QLabel(
            strings._("invoice_payments_summary").format(
                total=(int(self._invoice["total_cents"] or 0) / 100.0),
                currency=self._invoice["currency"] or "",
            )
        )
        root.addWidget(summary)

        form = QFormLayout()
        self.received_at = QDateEdit(QDate.currentDate())
        self.received_at.setCalendarPopup(True)
        self.received_at.setDisplayFormat("yyyy-MM-dd")
        if self._invoice["paid_at"]:
            qd = QDate.fromString(str(self._invoice["paid_at"]), "yyyy-MM-dd")
            if qd.isValid():
                self.received_at.setDate(qd)
        form.addRow(strings._("invoice_payment_received_on") + ":", self.received_at)

        self.invoice_amount = QDoubleSpinBox()
        self.invoice_amount.setDecimals(2)
        self.invoice_amount.setMaximum(999999999.99)
        self.invoice_amount.setSuffix(f" {self._invoice['currency'] or ''}")
        form.addRow(
            strings._("invoice_payment_applied_amount") + ":", self.invoice_amount
        )

        self.reporting_currency = QLineEdit(self.cfg.reporting_currency or "AUD")
        self.reporting_currency.setMaxLength(8)
        form.addRow(strings._("reporting_currency") + ":", self.reporting_currency)

        self.reporting_amount = QDoubleSpinBox()
        self.reporting_amount.setDecimals(2)
        self.reporting_amount.setMaximum(999999999.99)
        form.addRow(
            strings._("invoice_payment_reporting_amount") + ":", self.reporting_amount
        )

        self.note = QTextEdit()
        self.note.setMaximumHeight(72)
        form.addRow(strings._("invoice_payment_note") + ":", self.note)
        root.addLayout(form)

        self.help_label = QLabel(strings._("invoice_payment_reporting_help"))
        self.help_label.setWordWrap(True)
        root.addWidget(self.help_label)

        add_row = QHBoxLayout()
        self.outstanding_label = QLabel("")
        add_row.addWidget(self.outstanding_label)
        add_row.addStretch(1)
        add_btn = QPushButton(strings._("invoice_payment_record"))
        add_btn.clicked.connect(self._record_payment)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                strings._("invoice_payment_received_on"),
                strings._("invoice_payment_applied_amount"),
                strings._("invoice_payment_reporting_amount"),
                strings._("invoice_payment_exchange_rate"),
                strings._("invoice_payment_note"),
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            self.COL_DATE, QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(
            self.COL_INVOICE_AMOUNT, QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(
            self.COL_REPORTING_AMOUNT, QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(
            self.COL_RATE, QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(self.COL_NOTE, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        delete_btn = QPushButton(strings._("delete"))
        delete_btn.clicked.connect(self._delete_payment)
        btn_row.addWidget(delete_btn)
        btn_row.addStretch(1)
        close_btn = QPushButton(strings._("close"))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self.invoice_amount.valueChanged.connect(self._copy_same_currency_amount)
        self.reporting_currency.textChanged.connect(self._copy_same_currency_amount)
        self._reload()

    def _outstanding_cents(self) -> int:
        total = int(self._invoice["total_cents"] or 0)
        applied = self._db.get_invoice_payment_applied_cents(self._invoice_id)
        return max(0, total - applied)

    def _copy_same_currency_amount(self, *_args) -> None:
        if (
            self.reporting_currency.text().strip().upper()
            == str(self._invoice["currency"] or "").upper()
        ):
            self.reporting_amount.setValue(self.invoice_amount.value())

    def _reload(self) -> None:
        rows = self._db.get_invoice_payments(self._invoice_id)
        self.table.setRowCount(len(rows))
        invoice_currency = str(self._invoice["currency"] or "")
        for idx, row in enumerate(rows):
            date_item = QTableWidgetItem(row["received_at"] or "")
            date_item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
            self.table.setItem(idx, self.COL_DATE, date_item)
            applied = int(row["invoice_amount_cents"] or 0) / 100.0
            reporting = int(row["reporting_amount_cents"] or 0) / 100.0
            report_currency = row["reporting_currency"] or ""
            self.table.setItem(
                idx,
                self.COL_INVOICE_AMOUNT,
                QTableWidgetItem(f"{applied:,.2f} {invoice_currency}"),
            )
            self.table.setItem(
                idx,
                self.COL_REPORTING_AMOUNT,
                QTableWidgetItem(f"{reporting:,.2f} {report_currency}"),
            )
            rate = reporting / applied if applied else 0.0
            self.table.setItem(
                idx, self.COL_RATE, QTableWidgetItem(f"{rate:.6f}" if rate else "")
            )
            self.table.setItem(idx, self.COL_NOTE, QTableWidgetItem(row["note"] or ""))

        outstanding = self._outstanding_cents()
        self.outstanding_label.setText(
            strings._("invoice_payment_outstanding").format(
                amount=outstanding / 100.0,
                currency=invoice_currency,
            )
        )
        self.invoice_amount.setMaximum(max(0.0, outstanding / 100.0))
        self.invoice_amount.setValue(outstanding / 100.0)
        self._copy_same_currency_amount()

    def _record_payment(self) -> None:
        applied_cents = int(round(self.invoice_amount.value() * 100))
        reporting_cents = int(round(self.reporting_amount.value() * 100))
        reporting_currency = self.reporting_currency.text().strip().upper()
        if applied_cents <= 0 or reporting_cents <= 0 or not reporting_currency:
            QMessageBox.warning(
                self,
                strings._("error"),
                strings._("invoice_payment_amount_required"),
            )
            return
        try:
            self._db.add_invoice_payment(
                invoice_id=self._invoice_id,
                received_at=self.received_at.date().toString("yyyy-MM-dd"),
                invoice_amount_cents=applied_cents,
                reporting_currency=reporting_currency,
                reporting_amount_cents=reporting_cents,
                note=self.note.toPlainText().strip() or None,
            )
        except ValueError as exc:
            QMessageBox.warning(self, strings._("error"), str(exc))
            return

        self.note.clear()
        self.paymentsChanged.emit()
        self._invoice = self._db.get_invoice_with_project(self._invoice_id)
        self._reload()

    def _delete_payment(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, self.COL_DATE)
        if item is None:
            return
        payment_id = item.data(Qt.ItemDataRole.UserRole)
        if payment_id is None:
            return
        if (
            QMessageBox.question(
                self,
                strings._("delete"),
                strings._("invoice_payment_delete_confirm"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._db.delete_invoice_payment(int(payment_id))
        self.paymentsChanged.emit()
        self._invoice = self._db.get_invoice_with_project(self._invoice_id)
        self._reload()


class EarningsReportDialog(QDialog):
    """Earnings report using either invoice-date or payment-date recognition."""

    COL_MONTH = 0
    COL_NET = 1
    COL_TAX = 2
    COL_GROSS = 3
    COL_COUNT = 4

    def __init__(self, db: DBManager, parent=None):
        super().__init__(parent)
        self._db = db
        self.cfg = load_db_config()
        self._detail_rows = []
        self._monthly_rows: list[MonthlyEarnings] = []

        self.setWindowTitle(strings._("earnings_report"))
        self.resize(1040, 740)
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.reporting_currency = QLineEdit(self.cfg.reporting_currency or "AUD")
        self.reporting_currency.setMaxLength(8)
        form.addRow(strings._("reporting_currency") + ":", self.reporting_currency)

        self.basis_combo = QComboBox()
        self.basis_combo.addItem(strings._("earnings_basis_invoice"), "invoice")
        self.basis_combo.addItem(strings._("earnings_basis_payment"), "payment")
        form.addRow(strings._("earnings_basis") + ":", self.basis_combo)

        today = QDate.currentDate()
        quarter_start_month = ((today.month() - 1) // 3) * 3 + 1
        quarter_start = QDate(today.year(), quarter_start_month, 1)
        self.from_date = QDateEdit(quarter_start)
        self.from_date.setCalendarPopup(True)
        self.from_date.setDisplayFormat("yyyy-MM-dd")
        self.to_date = QDateEdit(today)
        self.to_date.setCalendarPopup(True)
        self.to_date.setDisplayFormat("yyyy-MM-dd")

        self.range_preset = QComboBox()
        self.range_preset.addItem(strings._("earnings_this_quarter"), "this_quarter")
        self.range_preset.addItem(
            strings._("earnings_previous_quarter"), "previous_quarter"
        )
        self.range_preset.addItem(strings._("this_year"), "this_year")
        self.range_preset.addItem(strings._("custom_range"), "custom")
        self.range_preset.currentIndexChanged.connect(self._on_preset_changed)
        range_row = QHBoxLayout()
        range_row.addWidget(self.range_preset)
        range_row.addWidget(self.from_date)
        range_row.addWidget(QLabel("—"))
        range_row.addWidget(self.to_date)
        form.addRow(strings._("date_range") + ":", range_row)
        root.addLayout(form)

        self.help_label = QLabel("")
        self.help_label.setWordWrap(True)
        root.addWidget(self.help_label)

        run_row = QHBoxLayout()
        run_row.addStretch(1)
        run_btn = QPushButton(strings._("run_report"))
        run_btn.clicked.connect(self._run_report)
        run_row.addWidget(run_btn)
        export_btn = QPushButton(strings._("export_csv"))
        export_btn.clicked.connect(self._export_csv)
        run_row.addWidget(export_btn)
        root.addLayout(run_row)

        self.chart = EarningsChart()
        root.addWidget(self.chart)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        root.addWidget(self.warning_label)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                strings._("earnings_month"),
                strings._("earnings_sales_ex_tax"),
                strings._("earnings_tax"),
                strings._("earnings_sales_inc_tax"),
                strings._("earnings_invoices"),
            ]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_MONTH, QHeaderView.ResizeMode.Stretch)
        for col in (self.COL_NET, self.COL_TAX, self.COL_GROSS, self.COL_COUNT):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 1)

        self.details = QTableWidget()
        self.details.setColumnCount(9)
        self.details.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self.details, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton(strings._("close"))
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

        self.basis_combo.currentIndexChanged.connect(self._run_report)
        self._run_report()

    def _on_preset_changed(self, _index: int) -> None:
        preset = self.range_preset.currentData()
        today = QDate.currentDate()
        qstart_month = ((today.month() - 1) // 3) * 3 + 1
        qstart = QDate(today.year(), qstart_month, 1)
        if preset == "this_quarter":
            start, end = qstart, today
        elif preset == "previous_quarter":
            prev_end = qstart.addDays(-1)
            prev_start_month = ((prev_end.month() - 1) // 3) * 3 + 1
            start = QDate(prev_end.year(), prev_start_month, 1)
            end = prev_end
        elif preset == "this_year":
            start, end = QDate(today.year(), 1, 1), today
        else:
            return
        self.from_date.setDate(start)
        self.to_date.setDate(end)

    @staticmethod
    def _tax_from_reporting_gross(row, gross: int) -> int:
        invoice_total = int(row["total_cents"] or 0)
        invoice_tax = int(row["tax_cents"] or 0)
        return int(round(gross * invoice_tax / invoice_total)) if invoice_total else 0

    def _configure_headers(self, basis: str) -> None:
        if basis == "invoice":
            self.help_label.setText(strings._("earnings_report_help_invoice"))
            self.table.horizontalHeaderItem(self.COL_COUNT).setText(
                strings._("earnings_invoices")
            )
            labels = [
                strings._("invoice_issue_date"),
                strings._("invoice_client_company"),
                strings._("project"),
                strings._("invoice_number"),
                strings._("invoice_currency"),
                strings._("invoice_total"),
                strings._("invoice_reporting_total"),
                strings._("earnings_tax"),
                strings._("invoice_reporting_note"),
            ]
        else:
            self.help_label.setText(strings._("earnings_report_help_payment"))
            self.table.horizontalHeaderItem(self.COL_COUNT).setText(
                strings._("earnings_payments")
            )
            labels = [
                strings._("invoice_payment_received_on"),
                strings._("invoice_client_company"),
                strings._("project"),
                strings._("invoice_number"),
                strings._("invoice_currency"),
                strings._("invoice_payment_applied_amount"),
                strings._("invoice_payment_reporting_amount"),
                strings._("earnings_tax"),
                strings._("invoice_payment_note"),
            ]
        self.details.setHorizontalHeaderLabels(labels)
        dheader = self.details.horizontalHeader()
        for col in range(8):
            dheader.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        dheader.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)

    def _run_report(self, _index: int | None = None) -> None:
        start = self.from_date.date().toString("yyyy-MM-dd")
        end = self.to_date.date().toString("yyyy-MM-dd")
        if end < start:
            QMessageBox.warning(
                self, strings._("error"), strings._("earnings_invalid_range")
            )
            return
        currency = self.reporting_currency.text().strip().upper()
        if not currency:
            QMessageBox.warning(
                self, strings._("error"), strings._("earnings_currency_required")
            )
            return
        self.reporting_currency.setText(currency)

        basis = str(self.basis_combo.currentData() or "invoice")
        self._configure_headers(basis)
        warnings: list[str] = []

        if basis == "invoice":
            all_rows = self._db.get_invoices_for_earnings_range(start, end)
            self._detail_rows = [
                row
                for row in all_rows
                if invoice_reporting_amount_cents(row, currency) is not None
            ]
            missing = len(all_rows) - len(self._detail_rows)
            self._monthly_rows = aggregate_invoices_by_month(
                self._detail_rows, currency, start, end
            )
            if missing:
                warnings.append(
                    strings._("earnings_missing_invoice_values").format(
                        count=missing, currency=currency
                    )
                )
        else:
            all_rows = self._db.get_payments_for_range(start, end)
            self._detail_rows = [
                row
                for row in all_rows
                if str(row["reporting_currency"] or "").upper() == currency
            ]
            skipped_currency = len(all_rows) - len(self._detail_rows)
            self._monthly_rows = aggregate_payments_by_month(
                self._detail_rows, start, end
            )
            legacy = self._db.get_paid_invoices_without_payments(start, end)
            if legacy:
                warnings.append(
                    strings._("earnings_unstructured_warning").format(count=len(legacy))
                )
            if skipped_currency:
                warnings.append(
                    strings._("earnings_other_currency_warning").format(
                        count=skipped_currency, currency=currency
                    )
                )

        self.table.setRowCount(len(self._monthly_rows))
        for idx, row in enumerate(self._monthly_rows):
            self.table.setItem(idx, self.COL_MONTH, QTableWidgetItem(row.month))
            self.table.setItem(
                idx,
                self.COL_NET,
                QTableWidgetItem(f"{row.sales_ex_tax_cents / 100.0:,.2f} {currency}"),
            )
            self.table.setItem(
                idx,
                self.COL_TAX,
                QTableWidgetItem(f"{row.tax_cents / 100.0:,.2f} {currency}"),
            )
            self.table.setItem(
                idx,
                self.COL_GROSS,
                QTableWidgetItem(f"{row.sales_inc_tax_cents / 100.0:,.2f} {currency}"),
            )
            self.table.setItem(
                idx, self.COL_COUNT, QTableWidgetItem(str(row.entry_count))
            )

        total_net = sum(row.sales_ex_tax_cents for row in self._monthly_rows)
        total_tax = sum(row.tax_cents for row in self._monthly_rows)
        total_gross = sum(row.sales_inc_tax_cents for row in self._monthly_rows)
        self.summary_label.setText(
            strings._("earnings_totals").format(
                ex_tax=f"{total_net / 100.0:,.2f}",
                tax=f"{total_tax / 100.0:,.2f}",
                inc_tax=f"{total_gross / 100.0:,.2f}",
                currency=currency,
            )
        )
        self.chart.set_rows(self._monthly_rows)
        self.warning_label.setText(" ".join(warnings))

        self.details.setRowCount(len(self._detail_rows))
        for idx, row in enumerate(self._detail_rows):
            if basis == "invoice":
                gross = invoice_reporting_amount_cents(row, currency)
                if gross is None:
                    raise RuntimeError(
                        "Invoice included in earnings report without a "
                        f"reporting amount: {row['invoice_number']!r}"
                    )

                tax = self._tax_from_reporting_gross(row, gross)
                values = [
                    row["issue_date"] or "",
                    row["client_company"] or "",
                    row["project_name"] or "",
                    row["invoice_number"] or "",
                    row["currency"] or "",
                    f"{int(row['total_cents'] or 0) / 100.0:,.2f} {row['currency'] or ''}",
                    f"{gross / 100.0:,.2f} {currency}",
                    f"{tax / 100.0:,.2f} {currency}",
                    row["reporting_note"] or "",
                ]
            else:
                gross = int(row["reporting_amount_cents"] or 0)
                tax = self._tax_from_reporting_gross(row, gross)
                values = [
                    row["received_at"] or "",
                    row["client_company"] or "",
                    row["project_name"] or "",
                    row["invoice_number"] or "",
                    row["currency"] or "",
                    f"{int(row['invoice_amount_cents'] or 0) / 100.0:,.2f} {row['currency'] or ''}",
                    f"{gross / 100.0:,.2f} {currency}",
                    f"{tax / 100.0:,.2f} {currency}",
                    row["note"] or "",
                ]
            for col, value in enumerate(values):
                self.details.setItem(idx, col, QTableWidgetItem(str(value)))

    def _export_csv(self) -> None:
        if not self._monthly_rows:
            QMessageBox.information(
                self, strings._("earnings_report"), strings._("earnings_no_data")
            )
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            strings._("export_csv"),
            "earnings.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        currency = self.reporting_currency.text().strip().upper()
        basis = str(self.basis_combo.currentData() or "invoice")
        count_label = (
            strings._("earnings_invoices")
            if basis == "invoice"
            else strings._("earnings_payments")
        )
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                [
                    strings._("earnings_month"),
                    strings._("earnings_sales_ex_tax"),
                    strings._("earnings_tax"),
                    strings._("earnings_sales_inc_tax"),
                    count_label,
                    strings._("reporting_currency"),
                    strings._("earnings_basis"),
                ]
            )
            for row in self._monthly_rows:
                writer.writerow(
                    [
                        row.month,
                        f"{row.sales_ex_tax_cents / 100.0:.2f}",
                        f"{row.tax_cents / 100.0:.2f}",
                        f"{row.sales_inc_tax_cents / 100.0:.2f}",
                        row.entry_count,
                        currency,
                        basis,
                    ]
                )
