from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import strings
from .db import DBManager
from .document_utils import open_document_from_db
from .invoices import InvoiceDialog


_WARNING_STYLES = {
    "unconfigured": "",
    "ok": "QLabel { padding: 6px; border: 1px solid #5b8f5b; border-radius: 4px; }",
    "warning": "QLabel { padding: 6px; border: 1px solid #b58900; border-radius: 4px; }",
    "reached": (
        "QLabel { padding: 6px; border: 1px solid #b85c00; "
        "border-radius: 4px; font-weight: bold; }"
    ),
    "exceeded": (
        "QLabel { padding: 6px; border: 1px solid #b00020; "
        "border-radius: 4px; font-weight: bold; }"
    ),
}


def hours_from_minutes(minutes: int | float | None) -> float:
    return float(minutes or 0) / 60.0


def minutes_from_hours(hours: float | int | None) -> int:
    return int(round(float(hours or 0) * 60))


def format_bucket_status(status: dict[str, object] | None) -> str:
    """Human-readable project bucket status used by project/time-log UIs."""
    if not status:
        return strings._("project_bucket_no_project")

    project = str(status.get("project_name") or "")
    state = str(status.get("state") or "unconfigured")
    baseline = hours_from_minutes(status.get("baseline_minutes"))
    logged = hours_from_minutes(status.get("logged_minutes"))
    used = hours_from_minutes(status.get("used_minutes"))
    ceiling = hours_from_minutes(status.get("bucket_ceiling_minutes"))
    remaining_minutes = status.get("remaining_minutes")
    remaining = (
        None if remaining_minutes is None else hours_from_minutes(remaining_minutes)
    )
    pct = status.get("percent_used")
    pct_text = "" if pct is None else f" ({float(pct):.1f}%)"

    if state == "unconfigured":
        return strings._("project_bucket_unconfigured").format(
            project=project,
            baseline=baseline,
            logged=logged,
            used=used,
        )

    remaining_text = "" if remaining is None else f", {remaining:.2f}h remaining"
    return strings._("project_bucket_status").format(
        project=project,
        used=used,
        ceiling=ceiling,
        percent=pct_text,
        remaining=remaining_text,
        baseline=baseline,
        logged=logged,
        state=strings._(f"project_bucket_state_{state}"),
    )


class ProjectsDialog(QDialog):
    """Project overview and prepaid-hours bucket manager."""

    SUM_PROJECT = 0
    SUM_LOGGED = 1
    SUM_BASELINE = 2
    SUM_USED = 3
    SUM_CEILING = 4
    SUM_REMAINING = 5
    SUM_STATE = 6
    SUM_TIME_LOGS = 7
    SUM_DOCS = 8
    SUM_INVOICES = 9

    LOG_DATE = 0
    LOG_ACTIVITY = 1
    LOG_NOTE = 2
    LOG_HOURS = 3
    LOG_CREATED = 4

    DOC_FILE = 0
    DOC_ADDED = 1
    DOC_DESCRIPTION = 2
    DOC_SIZE = 3

    INV_NUMBER = 0
    INV_ISSUE = 1
    INV_DUE = 2
    INV_TOTAL = 3
    INV_PAID = 4
    INV_DOCUMENT = 5

    def __init__(self, db: DBManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._reloading = False

        self.setWindowTitle(strings._("projects_title"))
        self.resize(1100, 700)

        root = QVBoxLayout(self)

        top_form = QFormLayout()
        top_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        root.addLayout(top_form)

        project_row = QHBoxLayout()
        self.project_combo = QComboBox()
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        project_row.addWidget(self.project_combo, 1)

        self.refresh_btn = QPushButton(strings._("refresh"))
        self.refresh_btn.clicked.connect(self.reload)
        project_row.addWidget(self.refresh_btn)
        top_form.addRow(strings._("project"), project_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        self.status_label.setMinimumHeight(
            self.status_label.fontMetrics().lineSpacing() * 3 + 18
        )
        top_form.addRow(strings._("project_bucket"), self.status_label)

        bucket_row = QHBoxLayout()
        self.baseline_spin = QDoubleSpinBox()
        self.baseline_spin.setRange(0.0, 1_000_000.0)
        self.baseline_spin.setDecimals(2)
        self.baseline_spin.setSingleStep(1.0)
        self.baseline_spin.setSuffix(" h")
        bucket_row.addWidget(QLabel(strings._("project_bucket_baseline")))
        bucket_row.addWidget(self.baseline_spin)

        self.ceiling_spin = QDoubleSpinBox()
        self.ceiling_spin.setRange(0.0, 1_000_000.0)
        self.ceiling_spin.setDecimals(2)
        self.ceiling_spin.setSingleStep(1.0)
        self.ceiling_spin.setSuffix(" h")
        bucket_row.addWidget(QLabel(strings._("project_bucket_ceiling")))
        bucket_row.addWidget(self.ceiling_spin)

        self.warn_spin = QDoubleSpinBox()
        self.warn_spin.setRange(0.0, 100.0)
        self.warn_spin.setDecimals(0)
        self.warn_spin.setSingleStep(5.0)
        self.warn_spin.setSuffix(" %")
        bucket_row.addWidget(QLabel(strings._("project_bucket_warn_at")))
        bucket_row.addWidget(self.warn_spin)

        self.save_bucket_btn = QPushButton(strings._("save"))
        self.save_bucket_btn.clicked.connect(self._save_bucket)
        bucket_row.addWidget(self.save_bucket_btn)

        top_form.addRow(strings._("project_bucket_settings"), bucket_row)

        topup_row = QHBoxLayout()
        self.topup_spin = QDoubleSpinBox()
        self.topup_spin.setRange(0.0, 1_000_000.0)
        self.topup_spin.setDecimals(2)
        self.topup_spin.setSingleStep(1.0)
        self.topup_spin.setValue(40.0)
        self.topup_spin.setSuffix(" h")
        topup_row.addWidget(self.topup_spin)

        self.topup_btn = QPushButton(strings._("project_bucket_add_to_ceiling"))
        self.topup_btn.clicked.connect(self._add_to_ceiling)
        topup_row.addWidget(self.topup_btn)

        self.invoice_prepaid_btn = QPushButton(
            strings._("project_bucket_invoice_prepaid")
        )
        self.invoice_prepaid_btn.clicked.connect(self._invoice_prepaid_hours)
        topup_row.addWidget(self.invoice_prepaid_btn)

        topup_row.addStretch(1)
        top_form.addRow(strings._("project_bucket_replenish"), topup_row)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(10)
        self.summary_table.setHorizontalHeaderLabels(
            [
                strings._("project"),
                strings._("project_hours_logged"),
                strings._("project_bucket_baseline"),
                strings._("project_bucket_used"),
                strings._("project_bucket_ceiling"),
                strings._("project_bucket_remaining"),
                strings._("status"),
                strings._("time_logs"),
                strings._("documents"),
                strings._("invoices"),
            ]
        )
        self.summary_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.summary_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary_table.itemSelectionChanged.connect(self._on_summary_selected)
        header = self.summary_table.horizontalHeader()
        header.setSectionResizeMode(self.SUM_PROJECT, QHeaderView.Stretch)
        for col in range(1, 10):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.tabs.addTab(self.summary_table, strings._("projects_summary_tab"))

        logs_tab = QWidget()
        logs_layout = QVBoxLayout(logs_tab)
        self.time_logs_table = QTableWidget()
        self.time_logs_table.setColumnCount(5)
        self.time_logs_table.setHorizontalHeaderLabels(
            [
                strings._("date"),
                strings._("activity"),
                strings._("note"),
                strings._("hours"),
                strings._("created_at"),
            ]
        )
        self.time_logs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.time_logs_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.time_logs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        log_header = self.time_logs_table.horizontalHeader()
        log_header.setSectionResizeMode(self.LOG_DATE, QHeaderView.ResizeToContents)
        log_header.setSectionResizeMode(self.LOG_ACTIVITY, QHeaderView.ResizeToContents)
        log_header.setSectionResizeMode(self.LOG_NOTE, QHeaderView.Stretch)
        log_header.setSectionResizeMode(self.LOG_HOURS, QHeaderView.ResizeToContents)
        log_header.setSectionResizeMode(self.LOG_CREATED, QHeaderView.ResizeToContents)
        logs_layout.addWidget(self.time_logs_table, 1)
        self.tabs.addTab(logs_tab, strings._("time_logs"))

        docs_tab = QWidget()
        docs_layout = QVBoxLayout(docs_tab)
        self.documents_table = QTableWidget()
        self.documents_table.setColumnCount(4)
        self.documents_table.setHorizontalHeaderLabels(
            [
                strings._("documents_col_file"),
                strings._("documents_col_added"),
                strings._("documents_col_description"),
                strings._("documents_col_size"),
            ]
        )
        self.documents_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.documents_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.documents_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.documents_table.itemDoubleClicked.connect(self._open_selected_document)
        doc_header = self.documents_table.horizontalHeader()
        doc_header.setSectionResizeMode(self.DOC_FILE, QHeaderView.Stretch)
        doc_header.setSectionResizeMode(self.DOC_ADDED, QHeaderView.ResizeToContents)
        doc_header.setSectionResizeMode(self.DOC_DESCRIPTION, QHeaderView.Stretch)
        doc_header.setSectionResizeMode(self.DOC_SIZE, QHeaderView.ResizeToContents)
        docs_layout.addWidget(self.documents_table, 1)

        docs_buttons = QHBoxLayout()
        docs_buttons.addStretch(1)
        self.open_doc_btn = QPushButton(strings._("documents_open"))
        self.open_doc_btn.clicked.connect(self._open_selected_document)
        docs_buttons.addWidget(self.open_doc_btn)
        docs_layout.addLayout(docs_buttons)
        self.tabs.addTab(docs_tab, strings._("documents"))

        invoices_tab = QWidget()
        invoices_layout = QVBoxLayout(invoices_tab)
        self.invoices_table = QTableWidget()
        self.invoices_table.setColumnCount(6)
        self.invoices_table.setHorizontalHeaderLabels(
            [
                strings._("invoice_number"),
                strings._("invoice_issue_date"),
                strings._("invoice_due_date"),
                strings._("invoice_total"),
                strings._("invoice_paid_at"),
                strings._("documents_col_file"),
            ]
        )
        self.invoices_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.invoices_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.invoices_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.invoices_table.itemDoubleClicked.connect(self._open_invoice_document)
        inv_header = self.invoices_table.horizontalHeader()
        inv_header.setSectionResizeMode(self.INV_NUMBER, QHeaderView.ResizeToContents)
        inv_header.setSectionResizeMode(self.INV_ISSUE, QHeaderView.ResizeToContents)
        inv_header.setSectionResizeMode(self.INV_DUE, QHeaderView.ResizeToContents)
        inv_header.setSectionResizeMode(self.INV_TOTAL, QHeaderView.ResizeToContents)
        inv_header.setSectionResizeMode(self.INV_PAID, QHeaderView.ResizeToContents)
        inv_header.setSectionResizeMode(self.INV_DOCUMENT, QHeaderView.Stretch)
        invoices_layout.addWidget(self.invoices_table, 1)

        invoice_buttons = QHBoxLayout()
        invoice_buttons.addStretch(1)
        self.open_invoice_doc_btn = QPushButton(
            strings._("project_open_invoice_document")
        )
        self.open_invoice_doc_btn.clicked.connect(self._open_invoice_document)
        invoice_buttons.addWidget(self.open_invoice_doc_btn)
        invoices_layout.addLayout(invoice_buttons)
        self.tabs.addTab(invoices_tab, strings._("invoices"))

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_btn = QPushButton(strings._("close"))
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        self.reload()

    def reload(self) -> None:
        current = self._current_project_id()
        self._load_projects(current)
        self._reload_summary()
        self._load_selected_project()

    def _load_projects(self, preferred: int | None = None) -> None:
        self._reloading = True
        try:
            self.project_combo.clear()
            for r in self._db.list_project_summaries():
                self.project_combo.addItem(str(r["project_name"]), int(r["project_id"]))
            if preferred is not None:
                idx = self.project_combo.findData(preferred)
                if idx >= 0:
                    self.project_combo.setCurrentIndex(idx)
            elif self.project_combo.count() > 0:
                self.project_combo.setCurrentIndex(0)
        finally:
            self._reloading = False

    def _current_project_id(self) -> int | None:
        data = self.project_combo.currentData()
        return int(data) if data is not None else None

    def _on_project_changed(self, _idx: int) -> None:
        if self._reloading:
            return
        self._load_selected_project()

    def _on_summary_selected(self) -> None:
        if self._reloading:
            return
        row = self.summary_table.currentRow()
        if row < 0:
            return
        item = self.summary_table.item(row, self.SUM_PROJECT)
        if item is None:
            return
        project_id = item.data(Qt.ItemDataRole.UserRole)
        if project_id is None:
            return
        idx = self.project_combo.findData(int(project_id))
        if idx >= 0:
            self.project_combo.setCurrentIndex(idx)

    def _state_for_row(self, r) -> str:
        baseline = int(r["baseline_minutes"] or 0)
        logged = int(r["logged_minutes"] or 0)
        used = baseline + logged
        ceiling = int(r["bucket_ceiling_minutes"] or 0)
        warn_at = float(r["warn_at_percent"] or 80.0)
        if ceiling <= 0:
            return "unconfigured"
        pct = used / ceiling * 100.0
        if used > ceiling:
            return "exceeded"
        if used == ceiling:
            return "reached"
        if pct >= warn_at:
            return "warning"
        return "ok"

    def _reload_summary(self) -> None:
        self._reloading = True
        try:
            rows = self._db.list_project_summaries()
            self.summary_table.setRowCount(len(rows))
            for row_idx, r in enumerate(rows):
                project_id = int(r["project_id"])
                baseline = int(r["baseline_minutes"] or 0)
                logged = int(r["logged_minutes"] or 0)
                used = baseline + logged
                ceiling = int(r["bucket_ceiling_minutes"] or 0)
                remaining = ceiling - used if ceiling > 0 else None
                state = self._state_for_row(r)

                project_item = QTableWidgetItem(str(r["project_name"]))
                project_item.setData(Qt.ItemDataRole.UserRole, project_id)
                self.summary_table.setItem(row_idx, self.SUM_PROJECT, project_item)
                self.summary_table.setItem(
                    row_idx,
                    self.SUM_LOGGED,
                    QTableWidgetItem(f"{hours_from_minutes(logged):.2f}"),
                )
                self.summary_table.setItem(
                    row_idx,
                    self.SUM_BASELINE,
                    QTableWidgetItem(f"{hours_from_minutes(baseline):.2f}"),
                )
                self.summary_table.setItem(
                    row_idx,
                    self.SUM_USED,
                    QTableWidgetItem(f"{hours_from_minutes(used):.2f}"),
                )
                ceiling_text = (
                    "" if ceiling <= 0 else f"{hours_from_minutes(ceiling):.2f}"
                )
                remaining_text = (
                    "" if remaining is None else f"{hours_from_minutes(remaining):.2f}"
                )
                state_text = strings._(f"project_bucket_state_{state}")
                self.summary_table.setItem(
                    row_idx, self.SUM_CEILING, QTableWidgetItem(ceiling_text)
                )
                self.summary_table.setItem(
                    row_idx, self.SUM_REMAINING, QTableWidgetItem(remaining_text)
                )
                self.summary_table.setItem(
                    row_idx, self.SUM_STATE, QTableWidgetItem(state_text)
                )
                self.summary_table.setItem(
                    row_idx,
                    self.SUM_TIME_LOGS,
                    QTableWidgetItem(str(r["time_log_count"] or 0)),
                )
                self.summary_table.setItem(
                    row_idx,
                    self.SUM_DOCS,
                    QTableWidgetItem(str(r["document_count"] or 0)),
                )
                self.summary_table.setItem(
                    row_idx,
                    self.SUM_INVOICES,
                    QTableWidgetItem(str(r["invoice_count"] or 0)),
                )
        finally:
            self._reloading = False

    def _load_selected_project(self) -> None:
        project_id = self._current_project_id()
        if project_id is None:
            self.status_label.setText(strings._("projects_none"))
            self.status_label.setStyleSheet("")
            self.baseline_spin.setValue(0.0)
            self.ceiling_spin.setValue(0.0)
            self.warn_spin.setValue(80.0)
            self.time_logs_table.setRowCount(0)
            self.documents_table.setRowCount(0)
            self.invoices_table.setRowCount(0)
            return

        status = self._db.project_bucket_status(project_id)
        self.status_label.setText(format_bucket_status(status))
        state = str(status.get("state") if status else "unconfigured")
        self.status_label.setStyleSheet(_WARNING_STYLES.get(state, ""))

        bucket = self._db.get_project_bucket(project_id)
        self.baseline_spin.setValue(
            hours_from_minutes(bucket["baseline_minutes"] if bucket else 0)
        )
        self.ceiling_spin.setValue(
            hours_from_minutes(bucket["bucket_ceiling_minutes"] if bucket else 0)
        )
        self.warn_spin.setValue(float(bucket["warn_at_percent"] if bucket else 80.0))

        self._reload_time_logs(project_id)
        self._reload_documents(project_id)
        self._reload_invoices(project_id)

    def _reload_time_logs(self, project_id: int) -> None:
        rows = self._db.time_logs_for_project(project_id)
        self.time_logs_table.setRowCount(len(rows))
        for row_idx, r in enumerate(rows):
            self.time_logs_table.setItem(
                row_idx, self.LOG_DATE, QTableWidgetItem(r["page_date"] or "")
            )
            self.time_logs_table.setItem(
                row_idx, self.LOG_ACTIVITY, QTableWidgetItem(r["activity_name"] or "")
            )
            self.time_logs_table.setItem(
                row_idx, self.LOG_NOTE, QTableWidgetItem(r["note"] or "")
            )
            self.time_logs_table.setItem(
                row_idx,
                self.LOG_HOURS,
                QTableWidgetItem(f"{hours_from_minutes(r['minutes']):.2f}"),
            )
            self.time_logs_table.setItem(
                row_idx, self.LOG_CREATED, QTableWidgetItem(r["created_at"] or "")
            )

    def _reload_documents(self, project_id: int) -> None:
        rows = self._db.documents_for_project(project_id)
        self.documents_table.setRowCount(len(rows))
        for row_idx, r in enumerate(rows):
            doc_id, _project_id, _project_name, file_name, description, size, added = r
            file_item = QTableWidgetItem(file_name or "")
            file_item.setData(Qt.ItemDataRole.UserRole, int(doc_id))
            self.documents_table.setItem(row_idx, self.DOC_FILE, file_item)
            self.documents_table.setItem(
                row_idx, self.DOC_ADDED, QTableWidgetItem(added or "")
            )
            self.documents_table.setItem(
                row_idx, self.DOC_DESCRIPTION, QTableWidgetItem(description or "")
            )
            self.documents_table.setItem(
                row_idx, self.DOC_SIZE, QTableWidgetItem(str(size or 0))
            )

    def _reload_invoices(self, project_id: int) -> None:
        rows = self._db.invoices_for_project_with_documents(project_id)
        self.invoices_table.setRowCount(len(rows))
        for row_idx, r in enumerate(rows):
            document_id = r["document_id"]
            file_name = r["document_file_name"] or ""
            num_item = QTableWidgetItem(r["invoice_number"] or "")
            num_item.setData(Qt.ItemDataRole.UserRole, int(r["id"]))
            self.invoices_table.setItem(row_idx, self.INV_NUMBER, num_item)
            self.invoices_table.setItem(
                row_idx, self.INV_ISSUE, QTableWidgetItem(r["issue_date"] or "")
            )
            self.invoices_table.setItem(
                row_idx, self.INV_DUE, QTableWidgetItem(r["due_date"] or "")
            )
            total = int(r["total_cents"] or 0) / 100.0
            currency = r["currency"] or ""
            self.invoices_table.setItem(
                row_idx,
                self.INV_TOTAL,
                QTableWidgetItem(f"{total:.2f} {currency}".strip()),
            )
            self.invoices_table.setItem(
                row_idx, self.INV_PAID, QTableWidgetItem(r["paid_at"] or "")
            )
            doc_item = QTableWidgetItem(file_name)
            doc_item.setData(
                Qt.ItemDataRole.UserRole,
                int(document_id) if document_id else None,
            )
            self.invoices_table.setItem(row_idx, self.INV_DOCUMENT, doc_item)

    def _save_bucket(self) -> None:
        project_id = self._current_project_id()
        if project_id is None:
            return
        self._db.upsert_project_bucket(
            project_id,
            minutes_from_hours(self.baseline_spin.value()),
            minutes_from_hours(self.ceiling_spin.value()),
            float(self.warn_spin.value()),
        )
        self.reload()

    def _add_to_ceiling(self) -> None:
        project_id = self._current_project_id()
        if project_id is None:
            return
        add_minutes = minutes_from_hours(self.topup_spin.value())
        if add_minutes <= 0:
            return
        self._db.add_to_project_bucket_ceiling(project_id, add_minutes)
        self.reload()

    def _invoice_prepaid_hours(self) -> None:
        project_id = self._current_project_id()
        if project_id is None:
            return

        hours = float(self.topup_spin.value())
        if hours <= 0.0:
            QMessageBox.warning(
                self,
                strings._("project_bucket_invoice_prepaid"),
                strings._("project_prepaid_invoice_hours_required"),
            )
            return

        today = QDate.currentDate().toString("yyyy-MM-dd")
        dialog = InvoiceDialog(
            self._db,
            project_id,
            today,
            today,
            time_rows=[],
            parent=self,
        )
        dialog.rb_summary.setChecked(True)
        dialog.summary_desc_edit.setText(
            strings._("project_prepaid_invoice_default_desc").format(hours=hours)
        )
        dialog.summary_hours_spin.setValue(hours)
        dialog._recalc_totals()

        if dialog.exec() == QDialog.Accepted:
            self.reload()

    def _selected_doc_id(self) -> tuple[int, str] | None:
        row = self.documents_table.currentRow()
        if row < 0:
            return None
        item = self.documents_table.item(row, self.DOC_FILE)
        if item is None:
            return None
        doc_id = item.data(Qt.ItemDataRole.UserRole)
        file_name = item.text()
        if doc_id is None or not file_name:
            return None
        return int(doc_id), file_name

    def _open_selected_document(self, *_args) -> None:
        selected = self._selected_doc_id()
        if not selected:
            QMessageBox.information(
                self,
                strings._("documents_open"),
                strings._("documents_select_document"),
            )
            return
        doc_id, file_name = selected
        open_document_from_db(self._db, doc_id, file_name, parent_widget=self)

    def _open_invoice_document(self, *_args) -> None:
        row = self.invoices_table.currentRow()
        if row < 0:
            return
        doc_item = self.invoices_table.item(row, self.INV_DOCUMENT)
        if doc_item is None:
            return
        doc_id = doc_item.data(Qt.ItemDataRole.UserRole)
        file_name = doc_item.text()
        if doc_id is None or not file_name:
            QMessageBox.information(
                self,
                strings._("project_open_invoice_document"),
                strings._("project_invoice_no_document"),
            )
            return
        open_document_from_db(self._db, int(doc_id), file_name, parent_widget=self)
