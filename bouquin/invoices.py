from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QDate, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPageLayout, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
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
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlcipher4 import dbapi2 as sqlite3

from . import strings
from .db import DBManager, TimeLogRow
from .reminders import Reminder, ReminderType
from .settings import load_db_config


class InvoiceDetailMode(str, Enum):
    DETAILED = "detailed"
    SUMMARY = "summary"


@dataclass
class InvoiceLineItem:
    description: str
    hours: float
    rate_cents: int
    amount_cents: int


# Default time of day for automatically created invoice reminders (HH:MM)
_INVOICE_REMINDER_TIME = "09:00"


def _invoice_due_reminder_text(project_name: str, invoice_number: str) -> str:
    """Build the human-readable text for an invoice due-date reminder.

    Using a single helper keeps the text consistent between creation and
    removal of reminders.
    """
    project = project_name.strip() or "(no project)"
    number = invoice_number.strip() or "?"
    return f"Invoice {number} for {project} is due"


class InvoiceDialog(QDialog):
    """
    Create an invoice for a project + date range from time logs.
    """

    COL_INCLUDE = 0
    COL_DATE = 1
    COL_ACTIVITY = 2
    COL_NOTE = 3
    COL_HOURS = 4
    COL_AMOUNT = 5

    remindersChanged = Signal()

    def __init__(
        self,
        db: DBManager,
        project_id: int,
        start_date_iso: str,
        end_date_iso: str,
        time_rows: list[TimeLogRow] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._db = db
        self._project_id = project_id
        self._start = start_date_iso
        self._end = end_date_iso

        self.cfg = load_db_config()

        if time_rows is not None:
            self._time_rows = time_rows
        else:
            # Fallback if dialog is ever used standalone
            self._time_rows = db.time_logs_for_range(
                project_id, start_date_iso, end_date_iso
            )

        self.setWindowTitle(strings._("invoice_dialog_title"))

        layout = QVBoxLayout(self)

        # -------- Header / metadata --------
        form = QFormLayout()

        # Project label
        proj_name = self._project_name()
        self.project_label = QLabel(proj_name)
        form.addRow(strings._("project") + ":", self.project_label)

        # Invoice number
        self.invoice_number_edit = QLineEdit(self._suggest_invoice_number())
        form.addRow(strings._("invoice_number") + ":", self.invoice_number_edit)

        # Issue + due dates
        today = QDate.currentDate()
        self.issue_date_edit = QDateEdit(today)
        self.issue_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.issue_date_edit.setCalendarPopup(True)
        form.addRow(strings._("invoice_issue_date") + ":", self.issue_date_edit)

        self.due_date_edit = QDateEdit(today.addDays(14))
        self.due_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.due_date_edit.setCalendarPopup(True)
        form.addRow(strings._("invoice_due_date") + ":", self.due_date_edit)

        # Billing defaults from project_billing
        pb = db.get_project_billing(project_id)
        if pb:
            (
                _pid,
                hourly_rate_cents,
                currency,
                tax_label,
                tax_rate_percent,
                client_name,
                client_company,
                client_address,
                client_email,
            ) = pb
        else:
            hourly_rate_cents = 0
            currency = "AUD"
            tax_label = "GST"
            tax_rate_percent = None
            client_name = client_company = client_address = client_email = ""

        # Currency
        self.currency_edit = QLineEdit(currency)
        form.addRow(strings._("invoice_currency") + ":", self.currency_edit)

        # Hourly rate
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0, 1_000_000)
        self.rate_spin.setDecimals(2)
        self.rate_spin.setValue(hourly_rate_cents / 100.0)
        self.rate_spin.valueChanged.connect(self._recalc_amounts)
        form.addRow(strings._("invoice_hourly_rate") + ":", self.rate_spin)

        # Tax
        self.tax_checkbox = QCheckBox(strings._("invoice_apply_tax"))
        self.tax_label = QLabel(strings._("invoice_tax_label") + ":")
        self.tax_label_edit = QLineEdit(tax_label or "")

        self.tax_rate_label = QLabel(strings._("invoice_tax_rate") + " %:")
        self.tax_rate_spin = QDoubleSpinBox()
        self.tax_rate_spin.setRange(0, 100)
        self.tax_rate_spin.setDecimals(2)

        tax_row = QHBoxLayout()
        tax_row.addWidget(self.tax_checkbox)
        tax_row.addWidget(self.tax_label)
        tax_row.addWidget(self.tax_label_edit)
        tax_row.addWidget(self.tax_rate_label)
        tax_row.addWidget(self.tax_rate_spin)
        form.addRow(strings._("invoice_tax") + ":", tax_row)

        if tax_rate_percent is None:
            self.tax_rate_spin.setValue(10.0)
            self.tax_checkbox.setChecked(False)
            self.tax_label.hide()
            self.tax_label_edit.hide()
            self.tax_rate_label.hide()
            self.tax_rate_spin.hide()
        else:
            self.tax_rate_spin.setValue(tax_rate_percent)
            self.tax_checkbox.setChecked(True)
            self.tax_label.show()
            self.tax_label_edit.show()
            self.tax_rate_label.show()
            self.tax_rate_spin.show()

        # When tax settings change, recalc totals
        self.tax_checkbox.toggled.connect(self._on_tax_toggled)
        self.tax_rate_spin.valueChanged.connect(self._recalc_totals)

        # Client info
        self.client_name_edit = QLineEdit(client_name or "")

        # Client company as an editable combo box with existing clients
        self.client_company_combo = QComboBox()
        self.client_company_combo.setEditable(True)

        companies = self._db.list_client_companies()
        # Add existing companies
        for comp in companies:
            if comp:
                self.client_company_combo.addItem(comp)

        # If this project already has a client_company, select it or set as text
        if client_company:
            idx = self.client_company_combo.findText(
                client_company, Qt.MatchFixedString
            )
            if idx >= 0:
                self.client_company_combo.setCurrentIndex(idx)
            else:
                self.client_company_combo.setEditText(client_company)

        # When the company text changes (selection or typed), try autofill
        self.client_company_combo.currentTextChanged.connect(
            self._on_client_company_changed
        )

        self.client_addr_edit = QTextEdit()
        self.client_addr_edit.setPlainText(client_address or "")
        self.client_email_edit = QLineEdit(client_email or "")

        form.addRow(strings._("invoice_client_name") + ":", self.client_name_edit)
        form.addRow(
            strings._("invoice_client_company") + ":", self.client_company_combo
        )
        form.addRow(strings._("invoice_client_address") + ":", self.client_addr_edit)
        form.addRow(strings._("invoice_client_email") + ":", self.client_email_edit)

        layout.addLayout(form)

        # -------- Detail mode + table --------
        mode_row = QHBoxLayout()
        self.rb_detailed = QRadioButton(strings._("invoice_mode_detailed"))
        self.rb_summary = QRadioButton(strings._("invoice_mode_summary"))
        self.rb_detailed.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.rb_detailed)
        self.mode_group.addButton(self.rb_summary)
        self.rb_detailed.toggled.connect(self._update_mode_enabled)
        mode_row.addWidget(self.rb_detailed)
        mode_row.addWidget(self.rb_summary)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # Detailed table (time entries)
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            [
                "",  # include checkbox
                strings._("date"),
                strings._("activity"),
                strings._("note"),
                strings._("invoice_hours"),
                strings._("invoice_amount"),
            ]
        )
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_INCLUDE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_DATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_ACTIVITY, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_NOTE, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_HOURS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_AMOUNT, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        self._populate_detailed_rows(hourly_rate_cents)
        self.table.itemChanged.connect(self._on_table_item_changed)

        # Summary line
        self.summary_desc_label = QLabel(strings._("invoice_summary_desc") + ":")
        self.summary_desc_edit = QLineEdit(strings._("invoice_summary_default_desc"))
        self.summary_hours_label = QLabel(strings._("invoice_summary_hours") + ":")
        self.summary_hours_spin = QDoubleSpinBox()
        self.summary_hours_spin.setRange(0, 10_000)
        self.summary_hours_spin.setDecimals(2)
        self.summary_hours_spin.setValue(self._total_hours_from_table())
        self.summary_hours_spin.valueChanged.connect(self._recalc_totals)

        summary_row = QHBoxLayout()
        summary_row.addWidget(self.summary_desc_label)
        summary_row.addWidget(self.summary_desc_edit)
        summary_row.addWidget(self.summary_hours_label)
        summary_row.addWidget(self.summary_hours_spin)
        layout.addLayout(summary_row)

        # -------- Totals --------
        totals_row = QHBoxLayout()
        self.subtotal_label = QLabel("0.00")
        self.tax_label_total = QLabel("0.00")
        self.total_label = QLabel("0.00")
        totals_row.addStretch()
        totals_row.addWidget(QLabel(strings._("invoice_subtotal") + ":"))
        totals_row.addWidget(self.subtotal_label)
        totals_row.addWidget(QLabel(strings._("invoice_tax_total") + ":"))
        totals_row.addWidget(self.tax_label_total)
        totals_row.addWidget(QLabel(strings._("invoice_total") + ":"))
        totals_row.addWidget(self.total_label)
        layout.addLayout(totals_row)

        # -------- Buttons --------
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_save = QPushButton(strings._("invoice_save_and_export"))
        self.btn_save.clicked.connect(self._on_save_clicked)
        btn_row.addWidget(self.btn_save)

        cancel_btn = QPushButton(strings._("cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._update_mode_enabled()
        self._recalc_totals()

    def _project_name(self) -> str:
        # relies on TimeLogRow including project_name
        if self._time_rows:
            return self._time_rows[0][3]
        # fallback: query projects table
        return self._db.list_projects_by_id(self._project_id)

    def _suggest_invoice_number(self) -> str:
        # Very simple example: YYYY-XXX based on count
        today = QDate.currentDate()
        year = today.toString("yyyy")
        last = self._db.get_invoice_count_by_project_id_and_year(
            self._project_id, f"{year}-%"
        )
        seq = int(last) + 1
        return f"{year}-{seq:03d}"

    def _create_due_date_reminder(
        self, invoice_id: int, invoice_number: str, due_date_iso: str
    ) -> None:
        """Create a one-off reminder on the invoice's due date.

        The reminder is purely informational and is keyed by its text so
        that it can be found and deleted later when the invoice is paid.
        """
        # No due date, nothing to remind about.
        if not due_date_iso:
            return

        # Build consistent text and create a Reminder dataclass instance.
        project_name = self._project_name()
        text = _invoice_due_reminder_text(project_name, invoice_number)

        reminder = Reminder(
            id=None,
            text=text,
            time_str=_INVOICE_REMINDER_TIME,
            reminder_type=ReminderType.ONCE,
            weekday=None,
            active=True,
            date_iso=due_date_iso,
        )

        try:
            # Save without failing the invoice flow if something goes wrong.
            self._db.save_reminder(reminder)
            self.remindersChanged.emit()
        except Exception:
            pass

    def _populate_detailed_rows(self, hourly_rate_cents: int) -> None:
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self._time_rows))
            rate = hourly_rate_cents / 100.0 if hourly_rate_cents else 0.0

            for row_idx, tl in enumerate(self._time_rows):
                (
                    tl_id,
                    page_date,
                    _proj_id,
                    _proj_name,
                    _act_id,
                    activity_name,
                    minutes,
                    note,
                    _created_at,
                ) = tl

                # include checkbox
                chk_item = QTableWidgetItem()
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Checked)
                chk_item.setData(Qt.UserRole, tl_id)
                self.table.setItem(row_idx, self.COL_INCLUDE, chk_item)

                self.table.setItem(row_idx, self.COL_DATE, QTableWidgetItem(page_date))
                self.table.setItem(
                    row_idx, self.COL_ACTIVITY, QTableWidgetItem(activity_name)
                )
                self.table.setItem(row_idx, self.COL_NOTE, QTableWidgetItem(note or ""))

                hours = minutes / 60.0

                # Hours - editable via spin box (override allowed)
                hours_spin = QDoubleSpinBox()
                hours_spin.setRange(0, 24)
                hours_spin.setDecimals(2)
                hours_spin.setValue(hours)
                hours_spin.valueChanged.connect(self._recalc_totals)
                self.table.setCellWidget(row_idx, self.COL_HOURS, hours_spin)

                amount = hours * rate
                amount_item = QTableWidgetItem(f"{amount:.2f}")
                amount_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                amount_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(row_idx, self.COL_AMOUNT, amount_item)
        finally:
            self.table.blockSignals(False)

    def _total_hours_from_table(self) -> float:
        total = 0.0
        for r in range(self.table.rowCount()):
            include_item = self.table.item(r, self.COL_INCLUDE)
            if include_item and include_item.checkState() == Qt.Checked:
                hours_widget = self.table.cellWidget(r, self.COL_HOURS)
                if isinstance(hours_widget, QDoubleSpinBox):
                    total += hours_widget.value()
        return total

    def _detail_line_items(self) -> list[InvoiceLineItem]:
        rate_cents = int(round(self.rate_spin.value() * 100))
        items: list[InvoiceLineItem] = []
        for r in range(self.table.rowCount()):
            include_item = self.table.item(r, self.COL_INCLUDE)
            if include_item and include_item.checkState() == Qt.Checked:
                date_str = self.table.item(r, self.COL_DATE).text()
                activity = self.table.item(r, self.COL_ACTIVITY).text()
                note = self.table.item(r, self.COL_NOTE).text()

                descr_parts = [date_str, activity]
                if note:
                    descr_parts.append(note)
                descr = " - ".join(descr_parts)

                hours_widget = self.table.cellWidget(r, self.COL_HOURS)
                hours = (
                    hours_widget.value()
                    if isinstance(hours_widget, QDoubleSpinBox)
                    else 0.0
                )
                amount_cents = int(round(hours * rate_cents))
                items.append(
                    InvoiceLineItem(
                        description=descr,
                        hours=hours,
                        rate_cents=rate_cents,
                        amount_cents=amount_cents,
                    )
                )
        return items

    def _summary_line_items(self) -> list[InvoiceLineItem]:
        rate_cents = int(round(self.rate_spin.value() * 100))
        hours = self.summary_hours_spin.value()
        amount_cents = int(round(hours * rate_cents))
        return [
            InvoiceLineItem(
                description=self.summary_desc_edit.text().strip() or "Services",
                hours=hours,
                rate_cents=rate_cents,
                amount_cents=amount_cents,
            )
        ]

    def _update_mode_enabled(self) -> None:
        detailed = self.rb_detailed.isChecked()
        self.table.setEnabled(detailed)
        if not detailed:
            self.summary_desc_label.show()
            self.summary_desc_edit.show()
            self.summary_hours_label.show()
            self.summary_hours_spin.show()
        else:
            self.summary_desc_label.hide()
            self.summary_desc_edit.hide()
            self.summary_hours_label.hide()
            self.summary_hours_spin.hide()
        self.resize(self.sizeHint().width(), self.sizeHint().height())
        self._recalc_totals()

    def _recalc_amounts(self) -> None:
        # Called when rate changes
        rate = self.rate_spin.value()
        for r in range(self.table.rowCount()):
            hours_widget = self.table.cellWidget(r, self.COL_HOURS)
            if isinstance(hours_widget, QDoubleSpinBox):
                hours = hours_widget.value()
                amount = hours * rate
                amount_item = self.table.item(r, self.COL_AMOUNT)
                if amount_item:
                    amount_item.setText(f"{amount:.2f}")
        self._recalc_totals()

    def _recalc_totals(self) -> None:
        if self.rb_detailed.isChecked():
            items = self._detail_line_items()
        else:
            items = self._summary_line_items()

        rate_cents = int(round(self.rate_spin.value() * 100))
        total_hours = sum(li.hours for li in items)
        subtotal_cents = int(round(total_hours * rate_cents))

        tax_rate = self.tax_rate_spin.value() if self.tax_checkbox.isChecked() else 0.0
        tax_cents = int(round(subtotal_cents * (tax_rate / 100.0)))
        total_cents = subtotal_cents + tax_cents

        self.subtotal_label.setText(f"{subtotal_cents / 100.0:.2f}")
        self.tax_label_total.setText(f"{tax_cents / 100.0:.2f}")
        self.total_label.setText(f"{total_cents / 100.0:.2f}")

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        """Handle changes to table items, particularly checkbox toggles."""
        if item and item.column() == self.COL_INCLUDE:
            self._recalc_totals()

    def _on_tax_toggled(self, checked: bool) -> None:
        # if on, show the other tax fields
        if checked:
            self.tax_label.show()
            self.tax_label_edit.show()
            self.tax_rate_label.show()
            self.tax_rate_spin.show()
        else:
            self.tax_label.hide()
            self.tax_label_edit.hide()
            self.tax_rate_label.hide()
            self.tax_rate_spin.hide()

        # If user just turned tax ON and the rate is 0, give a sensible default
        if checked and self.tax_rate_spin.value() == 0.0:
            self.tax_rate_spin.setValue(10.0)
        self.resize(self.sizeHint().width(), self.sizeHint().height())
        self._recalc_totals()

    def _on_client_company_changed(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        details = self._db.get_client_by_company(text)
        if not details:
            # New client - leave other fields as-is
            return

        # We don't touch the company combo text - user already chose/typed it.
        client_name, client_company, client_address, client_email = details
        if client_name:
            self.client_name_edit.setText(client_name)
        if client_address:
            self.client_addr_edit.setPlainText(client_address)
        if client_email:
            self.client_email_edit.setText(client_email)

    def _on_save_clicked(self) -> None:
        invoice_number = self.invoice_number_edit.text().strip()
        if not invoice_number:
            QMessageBox.warning(
                self,
                strings._("error"),
                strings._("invoice_number_required"),
            )
            return

        issue_date = self.issue_date_edit.date()
        due_date = self.due_date_edit.date()
        issue_date_iso = issue_date.toString("yyyy-MM-dd")
        due_date_iso = due_date.toString("yyyy-MM-dd")

        # Guard against due date before issue date
        if due_date.isValid() and issue_date.isValid() and due_date < issue_date:
            QMessageBox.warning(
                self,
                strings._("error"),
                strings._("invoice_due_before_issue"),
            )
            return

        detail_mode = (
            InvoiceDetailMode.DETAILED
            if self.rb_detailed.isChecked()
            else InvoiceDetailMode.SUMMARY
        )

        # Build line items & collect time_log_ids
        if detail_mode == InvoiceDetailMode.DETAILED:
            items = self._detail_line_items()
            time_log_ids: list[int] = []
            for r in range(self.table.rowCount()):
                include_item = self.table.item(r, self.COL_INCLUDE)
                if include_item and include_item.checkState() == Qt.Checked:
                    tl_id = int(include_item.data(Qt.UserRole))
                    time_log_ids.append(tl_id)
        else:
            items = self._summary_line_items()
            # In summary mode we still link all rows used for the report
            time_log_ids = [tl[0] for tl in self._time_rows]

        if not items:
            QMessageBox.warning(
                self,
                strings._("error"),
                strings._("invoice_no_items"),
            )
            return

        # Rate & tax info
        rate_cents = int(round(self.rate_spin.value() * 100))
        currency = self.currency_edit.text().strip()
        tax_label = self.tax_label_edit.text().strip() or None
        tax_rate_percent = (
            self.tax_rate_spin.value() if self.tax_checkbox.isChecked() else None
        )

        # Persist billing settings for this project (fills project_billing)
        self._db.upsert_project_billing(
            project_id=self._project_id,
            hourly_rate_cents=rate_cents,
            currency=currency,
            tax_label=tax_label,
            tax_rate_percent=tax_rate_percent,
            client_name=self.client_name_edit.text().strip() or None,
            client_company=self.client_company_combo.currentText().strip() or None,
            client_address=self.client_addr_edit.toPlainText().strip() or None,
            client_email=self.client_email_edit.text().strip() or None,
        )

        try:
            # Create invoice in DB
            invoice_id = self._db.create_invoice(
                project_id=self._project_id,
                invoice_number=invoice_number,
                issue_date=issue_date_iso,
                due_date=due_date_iso,
                currency=currency,
                tax_label=tax_label,
                tax_rate_percent=tax_rate_percent,
                detail_mode=detail_mode.value,
                line_items=[(li.description, li.hours, li.rate_cents) for li in items],
                time_log_ids=time_log_ids,
            )

            # Automatically create a reminder for the invoice due date
            if self.cfg.reminders:
                self._create_due_date_reminder(invoice_id, invoice_number, due_date_iso)

        except sqlite3.IntegrityError:
            # (project_id, invoice_number) must be unique
            QMessageBox.warning(
                self,
                strings._("error"),
                strings._("invoice_number_unique"),
            )
            return

        # Generate PDF
        pdf_path = self._export_pdf(invoice_id, items)
        # Save to Documents if the Documents feature is enabled
        if pdf_path and self.cfg.documents:
            doc_id = self._db.add_document_from_path(
                self._project_id,
                pdf_path,
                description=f"Invoice {invoice_number}",
            )
            self._db.set_invoice_document(invoice_id, doc_id)

        self.accept()

    def _export_pdf(self, invoice_id: int, items: list[InvoiceLineItem]) -> str | None:
        proj_name = self._project_name()
        safe_proj = proj_name.replace(" ", "_") or "project"
        invoice_number = self.invoice_number_edit.text().strip()
        filename = f"{safe_proj}_invoice_{invoice_number}.pdf"

        path, _ = QFileDialog.getSaveFileName(
            self,
            strings._("invoice_save_pdf_title"),
            filename,
            "PDF (*.pdf)",
        )
        if not path:
            return None

        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageOrientation(QPageLayout.Portrait)

        doc = QTextDocument()

        # Load company profile before building HTML
        profile = self._db.get_company_profile()
        self._company_profile = None
        if profile:
            name, address, phone, email, tax_id, payment_details, logo_bytes = profile
            self._company_profile = {
                "name": name,
                "address": address,
                "phone": phone,
                "email": email,
                "tax_id": tax_id,
                "payment_details": payment_details,
            }
            if logo_bytes:
                img = QImage.fromData(logo_bytes)
                if not img.isNull():
                    doc.addResource(
                        QTextDocument.ImageResource, QUrl("company_logo"), img
                    )

        html = self._build_invoice_html(items)
        doc.setHtml(html)
        doc.print_(printer)

        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        return path

    def _build_invoice_html(self, items: list[InvoiceLineItem]) -> str:
        # Monetary values based on current labels (these are kept in sync by _recalc_totals)
        try:
            subtotal = float(self.subtotal_label.text())
        except ValueError:
            subtotal = 0.0
        try:
            tax_total = float(self.tax_label_total.text())
        except ValueError:
            tax_total = 0.0
        total = subtotal + tax_total

        currency = self.currency_edit.text().strip()
        issue = self.issue_date_edit.date().toString("yyyy-MM-dd")
        due = self.due_date_edit.date().toString("yyyy-MM-dd")
        inv_no = self.invoice_number_edit.text().strip() or "-"
        proj = self._project_name()

        # --- Client block (Bill to) -------------------------------------
        client_lines = [
            self.client_company_combo.currentText().strip(),
            self.client_name_edit.text().strip(),
            self.client_addr_edit.toPlainText().strip(),
            self.client_email_edit.text().strip(),
        ]
        client_lines = [ln for ln in client_lines if ln]
        client_block = "<br>".join(
            line.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
            for line in client_lines
        )

        # --- Company block (From) ---------------------------------------
        company_html = ""
        if self._company_profile:
            cp = self._company_profile
            lines = [
                cp.get("name"),
                cp.get("address"),
                cp.get("phone"),
                cp.get("email"),
                "Tax ID/Business No: " + cp.get("tax_id"),
            ]
            lines = [ln for ln in lines if ln]
            company_html = "<br>".join(
                line.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
                for line in lines
            )

        logo_html = ""
        if self._company_profile:
            # "company_logo" resource is registered in _export_pdf
            logo_html = (
                '<img src="company_logo" '
                'style="max-width:140px; max-height:80px; margin-bottom:8px;">'
            )

        # --- Items table -------------------------------------------------
        item_rows_html = ""
        for idx, li in enumerate(items, start=1):
            desc = li.description or ""
            desc = (
                desc.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
            )
            hours_str = f"{li.hours:.2f}".rstrip("0").rstrip(".")
            price = li.rate_cents / 100.0
            amount = li.amount_cents / 100.0
            item_rows_html += f"""
                <tr>
                    <td style="padding:6px 8px; border-bottom:1px solid #dddddd; vertical-align:top; width:50%;">
                        {desc}
                    </td>
                    <td style="padding:6px 8px; border-bottom:1px solid #dddddd; text-align:center; white-space:nowrap; width:10%;">
                        {hours_str}
                    </td>
                    <td style="padding:6px 8px; border-bottom:1px solid #dddddd; text-align:right; white-space:nowrap; width:20%;">
                        {price:,.2f} {currency}
                    </td>
                    <td style="padding:6px 8px; border-bottom:1px solid #dddddd; text-align:right; white-space:nowrap; width:20%;">
                        {amount:,.2f} {currency}
                    </td>
                </tr>
            """

        if not item_rows_html:
            item_rows_html = """
                <tr>
                    <td colspan="4" style="padding:6px 8px; border-bottom:1px solid #dddddd;">
                        (No items)
                    </td>
                </tr>
            """

        # --- Tax summary line -------------------------------------------
        if tax_total > 0.0:
            tax_label = self.tax_label_edit.text().strip() or "Tax"
            tax_summary_text = f"{tax_label} has been added."
            tax_line_label = tax_label
            invoice_title = "TAX INVOICE"
        else:
            tax_summary_text = "No tax has been charged."
            tax_line_label = "Tax"
            invoice_title = "INVOICE"

        # --- Optional payment / terms text -----------------------------
        if self._company_profile and self._company_profile.get("payment_details"):
            raw_payment = self._company_profile["payment_details"]
        else:
            raw_payment = "Please pay by the due date. Thank you!"

        lines = [ln.strip() for ln in raw_payment.splitlines()]
        payment_text = "\n".join(lines).strip()

        # --- Build final HTML -------------------------------------------
        html = f"""
        <html>
        <head>
            <meta charset="utf-8">
        </head>
        <body style="font-family:'Helvetica','Arial',sans-serif; font-size:9pt; color:#222;">

            <!-- Header: logo/company left, INVOICE + meta right -->
            <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:16px;">
                <tr>
                    <td style="vertical-align:top; padding-right:12px; width:60%;">
                        {logo_html}
                        <div style="font-size:13pt; font-weight:bold; margin-bottom:4px;">
                            {company_html}
                        </div>
                    </td>
                    <td style="vertical-align:top; text-align:right; width:40%;">
                        <div style="font-size:20pt; font-weight:bold; margin-bottom:6px;">{invoice_title}</div>
                        <table cellspacing="0" cellpadding="2" style="font-size:9pt; display:inline-table;">
                            <tr>
                                <td style="padding:1px 4px; text-align:left;">Invoice no:</td>
                                <td style="padding:1px 4px; text-align:right;">{inv_no}</td>
                            </tr>
                            <tr>
                                <td style="padding:1px 4px; text-align:left;">Invoice date:</td>
                                <td style="padding:1px 4px; text-align:right;">{issue}</td>
                            </tr>
                            <tr>
                                <td style="padding:1px 4px; text-align:left;">Reference:</td>
                                <td style="padding:1px 4px; text-align:right;">{proj}</td>
                            </tr>
                            <tr>
                                <td style="padding:1px 4px; text-align:left;">Due date:</td>
                                <td style="padding:1px 4px; text-align:right;">{due}</td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>

            <!-- Bill to + overview -->
            <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:16px;">
                <tr>
                    <!-- Bill to -->
                    <td style="vertical-align:top; width:55%; padding-right:12px;">
                        <div style="font-weight:bold; font-size:10pt; margin-bottom:4px;">BILL TO</div>
                        <div>{client_block}</div>
                    </td>
                    <!-- Summary -->
                    <td style="vertical-align:top; width:45%; text-align:right;">
                        <table cellspacing="0" cellpadding="2" style="font-size:9pt; display:inline-table;">
                            <tr>
                                <td style="padding:1px 4px; text-align:left;">Subtotal</td>
                                <td style="padding:1px 4px; text-align:right;">{subtotal:,.2f} {currency}</td>
                            </tr>
                            <tr>
                                <td style="padding:1px 4px; text-align:left;">{tax_line_label}</td>
                                <td style="padding:1px 4px; text-align:right;">{tax_total:,.2f} {currency}</td>
                            </tr>
                            <tr>
                                <td style="padding:1px 4px; font-weight:bold; text-align:left;">TOTAL</td>
                                <td style="padding:1px 4px; font-weight:bold; text-align:right;">{total:,.2f} {currency}</td>
                            </tr>
                        </table>
                        <div style="margin-top:6px; font-size:8pt;">{tax_summary_text}</div>
                    </td>
                </tr>
            </table>

            <!-- Items table -->
            <table width="100%" cellspacing="0" cellpadding="0" style="border-top:1px solid #444444; border-bottom:1px solid #444444; margin-bottom:16px;">
                <tr style="background-color:#f3f3f3;">
                    <th style="padding:6px 8px; text-align:left; font-weight:bold; border-bottom:1px solid #dddddd;">ITEMS AND DESCRIPTION</th>
                    <th style="padding:6px 8px; text-align:center; font-weight:bold; border-bottom:1px solid #dddddd;">QTY/HRS</th>
                    <th style="padding:6px 8px; text-align:right; font-weight:bold; border-bottom:1px solid #dddddd;">PRICE</th>
                    <th style="padding:6px 8px; text-align:right; font-weight:bold; border-bottom:1px solid #dddddd;">AMOUNT ({currency})</th>
                </tr>
                {item_rows_html}
            </table>

            <!-- Payment details + amount due -->
            <table width="100%" cellspacing="0" cellpadding="0">
                <tr>
                    <td style="vertical-align:top; width:60%; padding-right:12px;">
                        <div style="font-weight:bold; margin-bottom:4px;">PAYMENT DETAILS</div>
                        <div style="font-size:8.5pt; line-height:1.3; white-space:pre-wrap;">
{payment_text}
                        </div>
                    </td>
                    <td style="vertical-align:top; width:40%; text-align:right;">
                        <!-- Amount due box -->
                        <table cellspacing="0" cellpadding="4" style="margin-left:auto; border:1px solid #444444; font-size:10pt;">
                            <tr>
                                <td style="font-weight:bold; text-align:left;">AMOUNT DUE</td>
                                <td style="font-weight:bold; text-align:right;">{total:,.2f} {currency}</td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>

        </body>
        </html>
        """

        return html


class InvoicesDialog(QDialog):
    """Manager for viewing and editing existing invoices."""

    COL_NUMBER = 0
    COL_PROJECT = 1
    COL_ISSUE_DATE = 2
    COL_DUE_DATE = 3
    COL_CURRENCY = 4
    COL_TAX_LABEL = 5
    COL_TAX_RATE = 6
    COL_SUBTOTAL = 7
    COL_TAX = 8
    COL_TOTAL = 9
    COL_PAID_AT = 10
    COL_PAYMENT_NOTE = 11

    remindersChanged = Signal()

    def __init__(
        self,
        db: DBManager,
        parent: QWidget | None = None,
        initial_project_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._reloading_invoices = False
        self.cfg = load_db_config()
        self.setWindowTitle(strings._("manage_invoices"))
        self.resize(1100, 500)

        root = QVBoxLayout(self)

        # --- Project selector -------------------------------------------------
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        root.addLayout(form)

        proj_row = QHBoxLayout()
        self.project_combo = QComboBox()
        proj_row.addWidget(self.project_combo, 1)
        form.addRow(strings._("project"), proj_row)

        self._reload_projects()
        self._select_initial_project(initial_project_id)

        self.project_combo.currentIndexChanged.connect(self._on_project_changed)

        # --- Table of invoices -----------------------------------------------
        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels(
            [
                strings._("invoice_number"),  # COL_NUMBER
                strings._("project"),  # COL_PROJECT
                strings._("invoice_issue_date"),  # COL_ISSUE_DATE
                strings._("invoice_due_date"),  # COL_DUE_DATE
                strings._("invoice_currency"),  # COL_CURRENCY
                strings._("invoice_tax_label"),  # COL_TAX_LABEL
                strings._("invoice_tax_rate"),  # COL_TAX_RATE
                strings._("invoice_subtotal"),  # COL_SUBTOTAL
                strings._("invoice_tax_total"),  # COL_TAX
                strings._("invoice_total"),  # COL_TOTAL
                strings._("invoice_paid_at"),  # COL_PAID_AT
                strings._("invoice_payment_note"),  # COL_PAYMENT_NOTE
            ]
        )

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_NUMBER, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_PROJECT, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COL_ISSUE_DATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_DUE_DATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_CURRENCY, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_TAX_LABEL, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_TAX_RATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_SUBTOTAL, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_TAX, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_TOTAL, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_PAID_AT, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COL_PAYMENT_NOTE, QHeaderView.Stretch)

        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )

        root.addWidget(self.table, 1)

        # Connect after constructing the table
        self.table.itemChanged.connect(self._on_item_changed)

        # --- Buttons ----------------------------------------------------------
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        delete_btn = QPushButton(strings._("delete"))
        delete_btn.clicked.connect(self._on_delete_clicked)
        btn_row.addWidget(delete_btn)

        close_btn = QPushButton(strings._("close"))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

        self._reload_invoices()

    # ----------------------------------------------------------------- deletion

    def _on_delete_clicked(self) -> None:
        """Delete the currently selected invoice."""
        row = self.table.currentRow()
        if row < 0:
            sel = self.table.selectionModel().selectedRows()
            if sel:
                row = sel[0].row()
        if row < 0:
            QMessageBox.information(
                self,
                strings._("delete"),
                strings._("invoice_required"),
            )
            return

        base_item = self.table.item(row, self.COL_NUMBER)
        if base_item is None:
            return

        inv_id = base_item.data(Qt.ItemDataRole.UserRole)
        if not inv_id:
            return

        invoice_number = (base_item.text() or "").strip() or "?"
        proj_item = self.table.item(row, self.COL_PROJECT)
        project_name = (proj_item.text() if proj_item is not None else "").strip()

        label = strings._("delete")
        prompt = (
            f"{label} '{invoice_number}'"
            + (f" ({project_name})" if project_name else "")
            + "?"
        )

        resp = QMessageBox.question(
            self,
            label,
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        # Remove any automatically created due-date reminder.
        if self.cfg.reminders:
            self._remove_invoice_due_reminder(row, int(inv_id))

        try:
            self._db.delete_invoice(int(inv_id))
        except Exception as e:
            QMessageBox.warning(
                self,
                strings._("error"),
                f"Failed to delete invoice: {e}",
            )
            return

        self._reload_invoices()

    # ------------------------------------------------------------------ helpers

    def _reload_projects(self) -> None:
        """Populate the project combo box."""
        self.project_combo.blockSignals(True)
        try:
            self.project_combo.clear()
            for proj_id, name in self._db.list_projects():
                self.project_combo.addItem(name, proj_id)
        finally:
            self.project_combo.blockSignals(False)

    def _select_initial_project(self, project_id: int | None) -> None:
        if project_id is None:
            if self.project_combo.count() > 0:
                self.project_combo.setCurrentIndex(0)
            return

        idx = self.project_combo.findData(project_id)
        if idx >= 0:
            self.project_combo.setCurrentIndex(idx)
        elif self.project_combo.count() > 0:
            self.project_combo.setCurrentIndex(0)

    def _current_project(self) -> int | None:
        idx = self.project_combo.currentIndex()
        if idx < 0:
            return None
        data = self.project_combo.itemData(idx)
        return int(data) if data is not None else None

    # ----------------------------------------------------------------- reloading

    def _on_project_changed(self, idx: int) -> None:
        _ = idx
        self._reload_invoices()

    def _reload_invoices(self) -> None:
        """Load invoices for the current project into the table."""
        self._reloading_invoices = True
        try:
            self.table.setRowCount(0)
            project_id = self._current_project()
            rows = self._db.get_all_invoices(project_id)

            self.table.setRowCount(len(rows) or 0)

            for row_idx, r in enumerate(rows):
                inv_id = int(r["id"])
                proj_name = r["project_name"] or ""
                invoice_number = r["invoice_number"] or ""
                issue_date = r["issue_date"] or ""
                due_date = r["due_date"] or ""
                currency = r["currency"] or ""
                tax_label = r["tax_label"] or ""
                tax_rate = (
                    r["tax_rate_percent"] if r["tax_rate_percent"] is not None else None
                )
                subtotal_cents = r["subtotal_cents"] or 0
                tax_cents = r["tax_cents"] or 0
                total_cents = r["total_cents"] or 0
                paid_at = r["paid_at"] or ""
                payment_note = r["payment_note"] or ""

                # Column 0: invoice number (store invoice_id in UserRole)
                num_item = QTableWidgetItem(invoice_number)
                num_item.setData(Qt.ItemDataRole.UserRole, inv_id)
                self.table.setItem(row_idx, self.COL_NUMBER, num_item)

                # Column 1: project name (read-only)
                proj_item = QTableWidgetItem(proj_name)
                proj_item.setFlags(proj_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_idx, self.COL_PROJECT, proj_item)

                # Column 2: issue date
                self.table.setItem(
                    row_idx, self.COL_ISSUE_DATE, QTableWidgetItem(issue_date)
                )

                # Column 3: due date
                self.table.setItem(
                    row_idx, self.COL_DUE_DATE, QTableWidgetItem(due_date or "")
                )

                # Column 4: currency
                self.table.setItem(
                    row_idx, self.COL_CURRENCY, QTableWidgetItem(currency)
                )

                # Column 5: tax label
                self.table.setItem(
                    row_idx, self.COL_TAX_LABEL, QTableWidgetItem(tax_label or "")
                )

                # Column 6: tax rate
                tax_rate_text = "" if tax_rate is None else f"{tax_rate:.2f}"
                self.table.setItem(
                    row_idx, self.COL_TAX_RATE, QTableWidgetItem(tax_rate_text)
                )

                # Column 7-9: amounts (cents → dollars)
                self.table.setItem(
                    row_idx,
                    self.COL_SUBTOTAL,
                    QTableWidgetItem(f"{subtotal_cents / 100.0:.2f}"),
                )
                self.table.setItem(
                    row_idx,
                    self.COL_TAX,
                    QTableWidgetItem(f"{tax_cents / 100.0:.2f}"),
                )
                self.table.setItem(
                    row_idx,
                    self.COL_TOTAL,
                    QTableWidgetItem(f"{total_cents / 100.0:.2f}"),
                )

                # Column 10: paid_at
                self.table.setItem(
                    row_idx, self.COL_PAID_AT, QTableWidgetItem(paid_at or "")
                )

                # Column 11: payment note
                self.table.setItem(
                    row_idx,
                    self.COL_PAYMENT_NOTE,
                    QTableWidgetItem(payment_note or ""),
                )

        finally:
            self._reloading_invoices = False

    # ----------------------------------------------------------------- editing

    def _remove_invoice_due_reminder(self, row: int, inv_id: int) -> None:
        """Delete any one-off reminder created for this invoice's due date.

        We look up reminders by the same text we used when creating them
        to avoid needing extra schema just for this linkage.
        """
        proj_item = self.table.item(row, self.COL_PROJECT)
        num_item = self.table.item(row, self.COL_NUMBER)
        if proj_item is None or num_item is None:
            return

        project_name = proj_item.text().strip()
        invoice_number = num_item.text().strip()
        if not project_name or not invoice_number:
            return

        target_text = _invoice_due_reminder_text(project_name, invoice_number)

        removed_any = False

        try:
            reminders = self._db.get_all_reminders()
        except Exception:
            return

        for reminder in reminders:
            if (
                reminder.id is not None
                and reminder.reminder_type == ReminderType.ONCE
                and reminder.text == target_text
            ):
                try:
                    self._db.delete_reminder(reminder.id)
                    removed_any = True
                except Exception:
                    # Best effort; if deletion fails we silently continue.
                    pass

        if removed_any:
            # Tell Reminders that reminders have changed
            self.remindersChanged.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Handle inline edits and write them back to the database."""
        if self._reloading_invoices:
            return

        row = item.row()
        col = item.column()

        base_item = self.table.item(row, self.COL_NUMBER)
        if base_item is None:
            return

        inv_id = base_item.data(Qt.ItemDataRole.UserRole)
        if not inv_id:
            return

        text = item.text().strip()

        def _reset_from_db(field: str, formatter=lambda v: v) -> None:
            """Reload a single field from DB and reset the cell."""
            self._reloading_invoices = True
            try:
                row_db = self._db.get_invoice_field_by_id(inv_id, field)

                if row_db is None:
                    return
                value = row_db[field]
                item.setText("" if value is None else formatter(value))
            finally:
                self._reloading_invoices = False

        # ---- Invoice number (unique per project) ----------------------------
        if col == self.COL_NUMBER:
            if not text:
                QMessageBox.warning(
                    self,
                    strings._("error"),
                    strings._("invoice_number_required"),
                )
                _reset_from_db("invoice_number", lambda v: v or "")
                return
            try:
                self._db.update_invoice_number(inv_id, text)
            except sqlite3.IntegrityError:
                QMessageBox.warning(
                    self,
                    strings._("error"),
                    strings._("invoice_number_unique"),
                )
                _reset_from_db("invoice_number", lambda v: v or "")
            return

        # ---- Dates: issue, due, paid_at (YYYY-MM-DD) ------------------------
        if col in (self.COL_ISSUE_DATE, self.COL_DUE_DATE, self.COL_PAID_AT):
            new_date: QDate | None = None
            if text:
                new_date = QDate.fromString(text, "yyyy-MM-dd")
                if not new_date.isValid():
                    QMessageBox.warning(
                        self,
                        strings._("error"),
                        strings._("invoice_invalid_date_format"),
                    )
                    field = {
                        self.COL_ISSUE_DATE: "issue_date",
                        self.COL_DUE_DATE: "due_date",
                        self.COL_PAID_AT: "paid_at",
                    }[col]
                    _reset_from_db(field, lambda v: v or "")
                    return

            # Cross-field validation: due/paid must not be before issue date
            issue_item = self.table.item(row, self.COL_ISSUE_DATE)
            issue_qd: QDate | None = None
            if issue_item is not None:
                issue_text = issue_item.text().strip()
                if issue_text:
                    issue_qd = QDate.fromString(issue_text, "yyyy-MM-dd")
                    if not issue_qd.isValid():
                        issue_qd = None

            if issue_qd is not None and new_date is not None:
                if col == self.COL_DUE_DATE and new_date < issue_qd:
                    QMessageBox.warning(
                        self,
                        strings._("error"),
                        strings._("invoice_due_before_issue"),
                    )
                    _reset_from_db("due_date", lambda v: v or "")
                    return
                if col == self.COL_PAID_AT and new_date < issue_qd:
                    QMessageBox.warning(
                        self,
                        strings._("error"),
                        strings._("invoice_paid_before_issue"),
                    )
                    _reset_from_db("paid_at", lambda v: v or "")
                    return

            field = {
                self.COL_ISSUE_DATE: "issue_date",
                self.COL_DUE_DATE: "due_date",
                self.COL_PAID_AT: "paid_at",
            }[col]

            self._db.set_invoice_field_by_id(inv_id, field, text or None)

            # If the invoice has just been marked as paid, remove any
            # auto-created reminder for its due date.
            if col == self.COL_PAID_AT and text and self.cfg.reminders:
                self._remove_invoice_due_reminder(row, inv_id)

            return

        # ---- Simple text fields: currency, tax label, payment_note ---
        if col in (
            self.COL_CURRENCY,
            self.COL_TAX_LABEL,
            self.COL_PAYMENT_NOTE,
        ):
            field = {
                self.COL_CURRENCY: "currency",
                self.COL_TAX_LABEL: "tax_label",
                self.COL_PAYMENT_NOTE: "payment_note",
            }[col]

            self._db.set_invoice_field_by_id(inv_id, field, text or None)

            if col == self.COL_CURRENCY and text:
                # Normalize currency code display
                self._reloading_invoices = True
                try:
                    item.setText(text.upper())
                finally:
                    self._reloading_invoices = False
            return

        # ---- Tax rate percent (float) ---------------------------------------
        if col == self.COL_TAX_RATE:
            if text:
                try:
                    rate = float(text)
                except ValueError:
                    QMessageBox.warning(
                        self,
                        strings._("error"),
                        strings._("invoice_invalid_tax_rate"),
                    )
                    _reset_from_db(
                        "tax_rate_percent",
                        lambda v: "" if v is None else f"{v:.2f}",
                    )
                    return
                value = rate
            else:
                value = None

            self._db.set_invoice_field_by_id(inv_id, "tax_rate_percent", value)
            return

        # ---- Monetary fields (subtotal, tax, total) in dollars --------------
        if col in (self.COL_SUBTOTAL, self.COL_TAX, self.COL_TOTAL):
            field = {
                self.COL_SUBTOTAL: "subtotal_cents",
                self.COL_TAX: "tax_cents",
                self.COL_TOTAL: "total_cents",
            }[col]
            if not text:
                cents = 0
            else:
                try:
                    value = float(text.replace(",", ""))
                except ValueError:
                    QMessageBox.warning(
                        self,
                        strings._("error"),
                        strings._("invoice_invalid_amount"),
                    )
                    _reset_from_db(
                        field,
                        lambda v: f"{(v or 0) / 100.0:.2f}",
                    )
                    return
                cents = int(round(value * 100))

            self._db.set_invoice_field_by_id(inv_id, field, cents)

            # Normalise formatting in the table
            self._reloading_invoices = True
            try:
                item.setText(f"{cents / 100.0:.2f}")
            finally:
                self._reloading_invoices = False
            return
