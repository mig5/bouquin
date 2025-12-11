from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
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
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import strings
from .db import DBManager, DocumentRow
from .settings import load_db_config
from .time_log import TimeCodeManagerDialog


class TodaysDocumentsWidget(QFrame):
    """
    Collapsible sidebar widget showing today's documents.
    """

    def __init__(
        self, db: DBManager, date_iso: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._current_date = date_iso

        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # Header (toggle + open-documents button)
        self.toggle_btn = QToolButton()
        self.toggle_btn.setText(strings._("todays_documents"))
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(False)
        self.toggle_btn.setArrowType(Qt.RightArrow)
        self.toggle_btn.clicked.connect(self._on_toggle)

        self.open_btn = QToolButton()
        self.open_btn.setIcon(
            self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        )
        self.open_btn.setToolTip(strings._("project_documents_title"))
        self.open_btn.setAutoRaise(True)
        self.open_btn.clicked.connect(self._open_documents_dialog)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.toggle_btn)
        header.addStretch(1)
        header.addWidget(self.open_btn)

        # Body: list of today's documents
        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(2)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setMaximumHeight(160)
        self.list.itemDoubleClicked.connect(self._open_selected_document)
        body_layout.addWidget(self.list)

        self.body.setVisible(False)

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.addLayout(header)
        main.addWidget(self.body)

        # Initial fill
        self.reload()

    # ----- public API ---------------------------------------------------

    def reload(self) -> None:
        """Refresh the list of today's documents."""
        self.list.clear()

        rows = self._db.todays_documents(self._current_date)
        if not rows:
            item = QListWidgetItem(strings._("todays_documents_none"))
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.list.addItem(item)
            return

        for doc_id, file_name, project_name in rows:
            label = file_name
            extra_parts = []
            if project_name:
                extra_parts.append(project_name)
            if extra_parts:
                label = f"{file_name} - " + " · ".join(extra_parts)

            item = QListWidgetItem(label)
            item.setData(
                Qt.ItemDataRole.UserRole,
                {"doc_id": doc_id, "file_name": file_name},
            )
            self.list.addItem(item)

    # ----- internals ----------------------------------------------------

    def set_current_date(self, date_iso: str) -> None:
        self._current_date = date_iso
        self.reload()

    def _on_toggle(self, checked: bool) -> None:
        self.body.setVisible(checked)
        self.toggle_btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        if checked:
            self.reload()

    def _open_selected_document(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        doc_id = data.get("doc_id")
        file_name = data.get("file_name") or ""
        if doc_id is None or not file_name:
            return
        self._open_document(int(doc_id), file_name)

    def _open_document(self, doc_id: int, file_name: str) -> None:
        """Open a document from the list."""
        from .document_utils import open_document_from_db

        open_document_from_db(self._db, doc_id, file_name, parent_widget=self)

    def _open_documents_dialog(self) -> None:
        """Open the full DocumentsDialog."""
        dlg = DocumentsDialog(self._db, self, current_date=self._current_date)
        dlg.exec()
        # Refresh after any changes
        self.reload()


class DocumentsDialog(QDialog):
    """
    Per-project document manager.

    - Choose a project
    - See list of attached documents
    - Add (from file), open (via temp file), delete
    - Inline-edit description
    - Inline-edit tags (comma-separated), using the global tags table
    """

    FILE_COL = 0
    TAGS_COL = 1
    DESC_COL = 2
    ADDED_COL = 3
    SIZE_COL = 4

    def __init__(
        self,
        db: DBManager,
        parent: QWidget | None = None,
        initial_project_id: Optional[int] = None,
        current_date: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self.cfg = load_db_config()
        self._reloading_docs = False
        self._search_text: str = ""
        self._current_date = current_date  # Store the current date for document uploads

        self.setWindowTitle(strings._("project_documents_title"))
        self.resize(900, 450)

        root = QVBoxLayout(self)

        # --- Project selector -------------------------------------------------
        form = QFormLayout()
        proj_row = QHBoxLayout()
        self.project_combo = QComboBox()
        self.manage_projects_btn = QPushButton(strings._("manage_projects"))
        self.manage_projects_btn.clicked.connect(self._manage_projects)
        proj_row.addWidget(self.project_combo, 1)
        proj_row.addWidget(self.manage_projects_btn)
        form.addRow(strings._("project"), proj_row)

        # --- Search box (all projects) ----------------------------------------
        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText(strings._("documents_search_placeholder"))
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        form.addRow(strings._("documents_search_label"), self.search_edit)

        root.addLayout(form)

        self.project_combo.currentIndexChanged.connect(self._on_project_changed)

        # --- Table of documents ----------------------------------------------
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                strings._("documents_col_file"),  # FILE_COL
                strings._("documents_col_tags"),  # TAGS_COL
                strings._("documents_col_description"),  # DESC_COL
                strings._("documents_col_added"),  # ADDED_COL
                strings._("documents_col_size"),  # SIZE_COL
            ]
        )

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.FILE_COL, QHeaderView.Stretch)
        header.setSectionResizeMode(self.TAGS_COL, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.DESC_COL, QHeaderView.Stretch)
        header.setSectionResizeMode(self.ADDED_COL, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.SIZE_COL, QHeaderView.ResizeToContents)

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        # Editable: tags + description
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked
        )

        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemDoubleClicked.connect(self._on_open_clicked)

        root.addWidget(self.table, 1)

        # --- Buttons ---------------------------------------------------------
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.add_btn = QPushButton(strings._("documents_add"))
        self.add_btn.clicked.connect(self._on_add_clicked)
        btn_row.addWidget(self.add_btn)

        self.open_btn = QPushButton(strings._("documents_open"))
        self.open_btn.clicked.connect(self._on_open_clicked)
        btn_row.addWidget(self.open_btn)

        self.delete_btn = QPushButton(strings._("documents_delete"))
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        btn_row.addWidget(self.delete_btn)

        close_btn = QPushButton(strings._("close"))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

        # Separator at bottom (purely cosmetic)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        root.addWidget(line)

        # Init data
        self._reload_projects()
        self._select_initial_project(initial_project_id)
        self._reload_documents()

    # --- Helpers -------------------------------------------------------------

    def _reload_projects(self) -> None:
        self.project_combo.blockSignals(True)
        try:
            self.project_combo.clear()
            for proj_id, name in self._db.list_projects():
                self.project_combo.addItem(name, proj_id)
        finally:
            self.project_combo.blockSignals(False)

    def _select_initial_project(self, project_id: Optional[int]) -> None:
        if project_id is None:
            if self.project_combo.count() > 0:
                self.project_combo.setCurrentIndex(0)
            return

        idx = self.project_combo.findData(project_id)
        if idx >= 0:
            self.project_combo.setCurrentIndex(idx)
        elif self.project_combo.count() > 0:
            self.project_combo.setCurrentIndex(0)

    def _current_project(self) -> Optional[int]:
        idx = self.project_combo.currentIndex()
        if idx < 0:
            return None
        proj_id = self.project_combo.itemData(idx)
        return int(proj_id) if proj_id is not None else None

    def _manage_projects(self) -> None:
        dlg = TimeCodeManagerDialog(self._db, focus_tab="projects", parent=self)
        dlg.exec()
        self._reload_projects()
        self._reload_documents()

    def _on_search_text_changed(self, text: str) -> None:
        """Update the in-memory search text and reload the table."""
        self._search_text = text
        self._reload_documents()

    def _reload_documents(self) -> None:

        search = (self._search_text or "").strip()

        self._reloading_docs = True
        try:
            self.table.setRowCount(0)

            if search:
                # Global search across all projects
                rows: list[DocumentRow] = self._db.search_documents(search)

            else:
                proj_id = self._current_project()
                if proj_id is None:
                    return

                rows = self._db.documents_for_project(proj_id)

            self.table.setRowCount(len(rows))

            for row_idx, r in enumerate(rows):
                (
                    doc_id,
                    _project_id,
                    project_name,
                    file_name,
                    description,
                    size_bytes,
                    uploaded_at,
                ) = r

                # Col 0: File
                file_item = QTableWidgetItem(file_name)
                file_item.setData(Qt.ItemDataRole.UserRole, doc_id)
                file_item.setFlags(file_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_idx, self.FILE_COL, file_item)

                # Col 1: Tags (comma-separated)
                tags = self._db.get_tags_for_document(doc_id)
                tag_names = [name for (_tid, name, _color) in tags]
                tags_text = ", ".join(tag_names)
                tags_item = QTableWidgetItem(tags_text)

                # If there is at least one tag, colour the cell using the first tag's colour
                if tags:
                    first_color = tags[0][2]
                    if first_color:
                        col = QColor(first_color)
                        tags_item.setBackground(col)
                        # Choose a readable text color
                        if col.lightness() < 128:
                            tags_item.setForeground(QColor("#ffffff"))
                        else:
                            tags_item.setForeground(QColor("#000000"))

                self.table.setItem(row_idx, self.TAGS_COL, tags_item)
                if not self.cfg.tags:
                    self.table.hideColumn(self.TAGS_COL)

                # Col 2: Description (editable)
                desc_item = QTableWidgetItem(description or "")
                self.table.setItem(row_idx, self.DESC_COL, desc_item)

                # Col 3: Added at (editable)
                added_label = uploaded_at
                added_item = QTableWidgetItem(added_label)
                self.table.setItem(row_idx, self.ADDED_COL, added_item)

                # Col 4: Size (not editable)
                size_item = QTableWidgetItem(self._format_size(size_bytes))
                size_item.setFlags(size_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_idx, self.SIZE_COL, size_item)
        finally:
            self._reloading_docs = False

    # --- Signals -------------------------------------------------------------

    def _on_project_changed(self, idx: int) -> None:
        _ = idx
        self._reload_documents()

    def _on_add_clicked(self) -> None:
        proj_id = self._current_project()
        if proj_id is None:
            QMessageBox.warning(
                self,
                strings._("project_documents_title"),
                strings._("documents_no_project_selected"),
            )
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            strings._("documents_add"),
            "",
            strings._("documents_file_filter_all"),
        )
        if not paths:
            return

        for path in paths:
            try:
                self._db.add_document_from_path(
                    proj_id, path, uploaded_at=self._current_date
                )
            except Exception as e:  # pragma: no cover
                QMessageBox.warning(
                    self,
                    strings._("project_documents_title"),
                    strings._("documents_add_failed").format(error=str(e)),
                )

        self._reload_documents()

    def _selected_doc_meta(self) -> tuple[Optional[int], Optional[str]]:
        row = self.table.currentRow()
        if row < 0:
            return None, None

        file_item = self.table.item(row, self.FILE_COL)
        if file_item is None:
            return None, None

        doc_id = file_item.data(Qt.ItemDataRole.UserRole)
        file_name = file_item.text()
        return (int(doc_id) if doc_id is not None else None, file_name)

    def _on_open_clicked(self, *args) -> None:
        doc_id, file_name = self._selected_doc_meta()
        if doc_id is None or not file_name:
            return
        self._open_document(doc_id, file_name)

    def _on_delete_clicked(self) -> None:
        doc_id, _file_name = self._selected_doc_meta()
        if doc_id is None:
            return

        resp = QMessageBox.question(
            self,
            strings._("project_documents_title"),
            strings._("documents_confirm_delete"),
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        self._db.delete_document(doc_id)
        self._reload_documents()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """
        Handle inline edits to Description, Tags, and Added date.
        """
        if self._reloading_docs or item is None:
            return

        row = item.row()
        col = item.column()

        file_item = self.table.item(row, self.FILE_COL)
        if file_item is None:
            return

        doc_id = file_item.data(Qt.ItemDataRole.UserRole)
        if doc_id is None:
            return

        doc_id = int(doc_id)

        # Description column
        if col == self.DESC_COL:
            desc = item.text().strip() or None
            self._db.update_document_description(doc_id, desc)
            return

        # Tags column
        if col == self.TAGS_COL:
            raw = item.text()
            # split on commas, strip, drop empties
            names = [p.strip() for p in raw.split(",") if p.strip()]
            self._db.set_tags_for_document(doc_id, names)

            # Re-normalise text to the canonical tag names stored in DB
            tags = self._db.get_tags_for_document(doc_id)
            tag_names = [name for (_tid, name, _color) in tags]
            tags_text = ", ".join(tag_names)

            self._reloading_docs = True
            try:
                item.setText(tags_text)
                # Reset / apply background based on first tag colour
                if tags:
                    first_color = tags[0][2]
                    if first_color:
                        col = QColor(first_color)
                        item.setBackground(col)
                        if col.lightness() < 128:
                            item.setForeground(QColor("#ffffff"))
                        else:
                            item.setForeground(QColor("#000000"))
                else:
                    # No tags: clear background / foreground to defaults
                    item.setBackground(QColor())
                    item.setForeground(QColor())
            finally:
                self._reloading_docs = False
            return

        # Added date column
        if col == self.ADDED_COL:
            date_str = item.text().strip()

            # Validate date format (YYYY-MM-DD)
            if not self._validate_date_format(date_str):
                QMessageBox.warning(
                    self,
                    strings._("project_documents_title"),
                    (
                        strings._("documents_invalid_date_format")
                        if hasattr(strings, "_")
                        and callable(getattr(strings, "_"))
                        and "documents_invalid_date_format" in dir(strings)
                        else f"Invalid date format. Please use YYYY-MM-DD format.\nExample: {date_str[:4]}-01-15"
                    ),
                )
                # Reload to reset the cell to its original value
                self._reload_documents()
                return

            # Update the database
            self._db.update_document_uploaded_at(doc_id, date_str)
            return

    # --- utils -------------------------------------------------------------

    def _validate_date_format(self, date_str: str) -> bool:
        """
        Validate that a date string is in YYYY-MM-DD format.

        Returns True if valid, False otherwise.
        """
        import re
        from datetime import datetime

        # Check basic format with regex
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return False

        # Validate it's a real date
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def _open_document(self, doc_id: int, file_name: str) -> None:
        """
        Fetch BLOB from DB, write to a temporary file, and open with default app.
        """
        from .document_utils import open_document_from_db

        open_document_from_db(self._db, doc_id, file_name, parent_widget=self)

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """
        Human-readable file size.
        """
        if size_bytes < 1024:
            return f"{size_bytes} B"
        kb = size_bytes / 1024.0
        if kb < 1024:
            return f"{kb:.1f} KB"
        mb = kb / 1024.0
        if mb < 1024:
            return f"{mb:.1f} MB"
        gb = mb / 1024.0
        return f"{gb:.1f} GB"
