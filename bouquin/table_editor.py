from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHeaderView,
    QWidget,
)

from . import strings


class TableEditorDialog(QDialog):
    """Dialog for editing markdown tables visually."""

    def __init__(self, table_text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(strings._("edit_table"))
        self.setMinimumSize(600, 400)

        layout = QVBoxLayout(self)

        # Parse the table
        self.table_widget = QTableWidget()
        self._parse_table(table_text)

        # Allow editing
        self.table_widget.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive
        )
        layout.addWidget(self.table_widget)

        # Buttons for table operations
        btn_layout = QHBoxLayout()

        add_row_btn = QPushButton(strings._("add_row"))
        add_row_btn.clicked.connect(self._add_row)
        btn_layout.addWidget(add_row_btn)

        add_col_btn = QPushButton(strings._("add_column"))
        add_col_btn.clicked.connect(self._add_column)
        btn_layout.addWidget(add_col_btn)

        del_row_btn = QPushButton(strings._("delete_row"))
        del_row_btn.clicked.connect(self._delete_row)
        btn_layout.addWidget(del_row_btn)

        del_col_btn = QPushButton(strings._("delete_column"))
        del_col_btn.clicked.connect(self._delete_column)
        btn_layout.addWidget(del_col_btn)

        layout.addLayout(btn_layout)

        # OK/Cancel buttons
        btn_layout2 = QHBoxLayout()
        btn_layout2.addStretch()

        ok_btn = QPushButton(strings._("ok"))
        ok_btn.clicked.connect(self.accept)
        ok_btn.setDefault(True)
        btn_layout2.addWidget(ok_btn)

        cancel_btn = QPushButton(strings._("cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout2.addWidget(cancel_btn)

        layout.addLayout(btn_layout2)

    def _parse_table(self, text: str):
        """Parse markdown table into QTableWidget."""
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        if len(lines) < 1:
            return

        # Parse header
        header_line = lines[0]
        # Split by | and remove first/last empty strings from leading/trailing pipes
        header_parts = header_line.split("|")
        if len(header_parts) > 0 and not header_parts[0].strip():
            header_parts = header_parts[1:]
        if len(header_parts) > 0 and not header_parts[-1].strip():
            header_parts = header_parts[:-1]
        headers = [cell.strip() for cell in header_parts]

        # Check if line[1] is a separator line (contains ---)
        # If not, treat all lines after header as data
        start_data_idx = 1
        if len(lines) > 1:
            separator_check = lines[1]
            # Split by | and remove first/last empty strings
            sep_parts = separator_check.split("|")
            if len(sep_parts) > 0 and not sep_parts[0].strip():
                sep_parts = sep_parts[1:]
            if len(sep_parts) > 0 and not sep_parts[-1].strip():
                sep_parts = sep_parts[:-1]
            cells = [cell.strip() for cell in sep_parts]
            # Check if this looks like a separator (contains --- or :--: etc)
            if cells and all(re.match(r"^:?-+:?$", cell) for cell in cells):
                start_data_idx = 2  # Skip separator line

        # Parse data rows
        data_rows = []
        for line in lines[start_data_idx:]:
            # Split by | and remove first/last empty strings from leading/trailing pipes
            parts = line.split("|")
            if len(parts) > 0 and not parts[0].strip():
                parts = parts[1:]
            if len(parts) > 0 and not parts[-1].strip():
                parts = parts[:-1]
            cells = [cell.strip() for cell in parts]
            data_rows.append(cells)

        # Set up table
        self.table_widget.setColumnCount(len(headers))
        self.table_widget.setHorizontalHeaderLabels(headers)
        self.table_widget.setRowCount(len(data_rows))

        # Populate cells
        for row_idx, row_data in enumerate(data_rows):
            for col_idx, cell_text in enumerate(row_data):
                if col_idx < len(headers):
                    item = QTableWidgetItem(cell_text)
                    self.table_widget.setItem(row_idx, col_idx, item)

    @Slot()
    def _add_row(self):
        """Add a new row to the table."""
        row_count = self.table_widget.rowCount()
        self.table_widget.insertRow(row_count)

        # Add empty items
        for col in range(self.table_widget.columnCount()):
            self.table_widget.setItem(row_count, col, QTableWidgetItem(""))

    @Slot()
    def _add_column(self):
        """Add a new column to the table."""
        col_count = self.table_widget.columnCount()
        self.table_widget.insertColumn(col_count)
        self.table_widget.setHorizontalHeaderItem(
            col_count, QTableWidgetItem(strings._("column") + f"{col_count + 1}")
        )

        # Add empty items
        for row in range(self.table_widget.rowCount()):
            self.table_widget.setItem(row, col_count, QTableWidgetItem(""))

    @Slot()
    def _delete_row(self):
        """Delete the currently selected row."""
        current_row = self.table_widget.currentRow()
        if current_row >= 0:
            self.table_widget.removeRow(current_row)

    @Slot()
    def _delete_column(self):
        """Delete the currently selected column."""
        current_col = self.table_widget.currentColumn()
        if current_col >= 0:
            self.table_widget.removeColumn(current_col)

    def get_markdown_table(self) -> str:
        """Convert the table back to markdown format."""
        if self.table_widget.rowCount() == 0 or self.table_widget.columnCount() == 0:
            return ""

        lines = []

        # Header
        headers = []
        for col in range(self.table_widget.columnCount()):
            header_item = self.table_widget.horizontalHeaderItem(col)
            headers.append(
                header_item.text()
                if header_item
                else strings._("column") + f"{col + 1}"
            )
        lines.append("| " + " | ".join(headers) + " |")

        # Separator
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        # Data rows
        for row in range(self.table_widget.rowCount()):
            cells = []
            for col in range(self.table_widget.columnCount()):
                item = self.table_widget.item(row, col)
                cells.append(item.text() if item else "")
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines)


def find_table_at_cursor(text: str, cursor_pos: int) -> Optional[tuple[int, int, str]]:
    """
    Find a markdown table containing the cursor position.
    Returns (start_pos, end_pos, table_text) or None.
    """
    lines = text.split("\n")

    # Find which line the cursor is on
    current_pos = 0
    cursor_line_idx = 0
    for i, line in enumerate(lines):
        if current_pos + len(line) >= cursor_pos:
            cursor_line_idx = i
            break
        current_pos += len(line) + 1  # +1 for newline

    # Check if cursor line is part of a table
    if not _is_table_line(lines[cursor_line_idx]):
        return None

    # Find table start
    start_idx = cursor_line_idx
    while start_idx > 0 and _is_table_line(lines[start_idx - 1]):
        start_idx -= 1

    # Find table end
    end_idx = cursor_line_idx
    while end_idx < len(lines) - 1 and _is_table_line(lines[end_idx + 1]):
        end_idx += 1

    # Extract table text
    table_lines = lines[start_idx : end_idx + 1]
    table_text = "\n".join(table_lines)

    # Calculate character positions
    start_pos = sum(len(lines[i]) + 1 for i in range(start_idx))
    end_pos = start_pos + len(table_text)

    return (start_pos, end_pos, table_text)


def _is_table_line(line: str) -> bool:
    """Check if a line is part of a markdown table."""
    stripped = line.strip()
    if not stripped:
        return False

    # Table lines start and end with |
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return False

    # Must have at least one | in between
    return stripped.count("|") >= 2
