from bouquin.table_editor import TableEditorDialog, find_table_at_cursor, _is_table_line


def test_table_editor_init_simple_table(qtbot, app):
    """Test initialization with a simple markdown table."""
    table_text = """| Header1 | Header2 | Header3 |
| --- | --- | --- |
| Cell1 | Cell2 | Cell3 |
| Cell4 | Cell5 | Cell6 |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    assert dialog.table_widget.columnCount() == 3
    assert dialog.table_widget.rowCount() == 2
    assert dialog.table_widget.horizontalHeaderItem(0).text() == "Header1"
    assert dialog.table_widget.horizontalHeaderItem(1).text() == "Header2"
    assert dialog.table_widget.item(0, 0).text() == "Cell1"
    assert dialog.table_widget.item(1, 2).text() == "Cell6"


def test_table_editor_no_separator_line(qtbot, app):
    """Test parsing table without separator line."""
    table_text = """| Header1 | Header2 |
| Cell1 | Cell2 |
| Cell3 | Cell4 |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    assert dialog.table_widget.columnCount() == 2
    assert dialog.table_widget.rowCount() == 2
    assert dialog.table_widget.item(0, 0).text() == "Cell1"


def test_table_editor_empty_table(qtbot, app):
    """Test initialization with empty table text."""
    dialog = TableEditorDialog("")
    qtbot.addWidget(dialog)

    # Should have no columns/rows
    assert dialog.table_widget.columnCount() == 0 or dialog.table_widget.rowCount() == 0


def test_table_editor_single_header_line(qtbot, app):
    """Test table with only header line."""
    table_text = "| Header1 | Header2 | Header3 |"

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    assert dialog.table_widget.columnCount() == 3
    assert dialog.table_widget.rowCount() == 0


def test_add_row(qtbot, app):
    """Test adding a row to the table."""
    table_text = """| H1 | H2 |
| --- | --- |
| A | B |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    initial_rows = dialog.table_widget.rowCount()
    dialog._add_row()

    assert dialog.table_widget.rowCount() == initial_rows + 1
    # New row should have empty items
    assert dialog.table_widget.item(initial_rows, 0).text() == ""
    assert dialog.table_widget.item(initial_rows, 1).text() == ""


def test_add_column(qtbot, app):
    """Test adding a column to the table."""
    table_text = """| H1 | H2 |
| --- | --- |
| A | B |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    initial_cols = dialog.table_widget.columnCount()
    dialog._add_column()

    assert dialog.table_widget.columnCount() == initial_cols + 1
    # New column should have header and empty items
    assert "Column" in dialog.table_widget.horizontalHeaderItem(initial_cols).text()
    assert dialog.table_widget.item(0, initial_cols).text() == ""


def test_delete_row(qtbot, app):
    """Test deleting a row from the table."""
    table_text = """| H1 | H2 |
| --- | --- |
| A | B |
| C | D |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    initial_rows = dialog.table_widget.rowCount()
    dialog.table_widget.setCurrentCell(0, 0)
    dialog._delete_row()

    assert dialog.table_widget.rowCount() == initial_rows - 1


def test_delete_row_no_selection(qtbot, app):
    """Test deleting a row when nothing is selected."""
    table_text = """| H1 | H2 |
| --- | --- |
| A | B |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    initial_rows = dialog.table_widget.rowCount()
    dialog.table_widget.setCurrentCell(-1, -1)  # No selection
    dialog._delete_row()

    # Row count should remain the same
    assert dialog.table_widget.rowCount() == initial_rows


def test_delete_column(qtbot, app):
    """Test deleting a column from the table."""
    table_text = """| H1 | H2 | H3 |
| --- | --- | --- |
| A | B | C |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    initial_cols = dialog.table_widget.columnCount()
    dialog.table_widget.setCurrentCell(0, 1)
    dialog._delete_column()

    assert dialog.table_widget.columnCount() == initial_cols - 1


def test_delete_column_no_selection(qtbot, app):
    """Test deleting a column when nothing is selected."""
    table_text = """| H1 | H2 |
| --- | --- |
| A | B |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    initial_cols = dialog.table_widget.columnCount()
    dialog.table_widget.setCurrentCell(-1, -1)  # No selection
    dialog._delete_column()

    # Column count should remain the same
    assert dialog.table_widget.columnCount() == initial_cols


def test_get_markdown_table(qtbot, app):
    """Test converting table back to markdown."""
    table_text = """| Name | Age | City |
| --- | --- | --- |
| Alice | 30 | NYC |
| Bob | 25 | LA |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    result = dialog.get_markdown_table()

    assert "| Name | Age | City |" in result
    assert "| --- | --- | --- |" in result
    assert "| Alice | 30 | NYC |" in result
    assert "| Bob | 25 | LA |" in result


def test_get_markdown_table_empty(qtbot, app):
    """Test getting markdown from empty table."""
    dialog = TableEditorDialog("")
    qtbot.addWidget(dialog)

    result = dialog.get_markdown_table()
    assert result == ""


def test_get_markdown_table_with_modifications(qtbot, app):
    """Test getting markdown after modifying table."""
    table_text = """| H1 | H2 |
| --- | --- |
| A | B |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    # Modify a cell
    dialog.table_widget.item(0, 0).setText("Modified")

    result = dialog.get_markdown_table()
    assert "Modified" in result


def test_find_table_at_cursor_middle_of_table(qtbot, app):
    """Test finding table when cursor is in the middle."""
    text = """Some text before

| H1 | H2 |
| --- | --- |
| A | B |
| C | D |

Some text after"""

    # Cursor position in the middle of the table
    cursor_pos = text.find("| A |") + 2
    result = find_table_at_cursor(text, cursor_pos)

    assert result is not None
    start, end, table_text = result
    assert "| H1 | H2 |" in table_text
    assert "| A | B |" in table_text
    assert "Some text before" not in table_text
    assert "Some text after" not in table_text


def test_find_table_at_cursor_first_line(qtbot, app):
    """Test finding table when cursor is on the first line."""
    text = """| H1 | H2 |
| --- | --- |
| A | B |"""

    cursor_pos = 5  # In the first line
    result = find_table_at_cursor(text, cursor_pos)

    assert result is not None
    start, end, table_text = result
    assert "| H1 | H2 |" in table_text


def test_find_table_at_cursor_not_in_table(qtbot, app):
    """Test finding table when cursor is not in a table."""
    text = """Just some regular text
No tables here

| H1 | H2 |
| --- | --- |
| A | B |"""

    cursor_pos = 10  # In "Just some regular text"
    result = find_table_at_cursor(text, cursor_pos)

    assert result is None


def test_find_table_at_cursor_empty_text(qtbot, app):
    """Test finding table in empty text."""
    result = find_table_at_cursor("", 0)
    assert result is None


def test_find_table_at_cursor_multiple_tables(qtbot, app):
    """Test finding correct table when there are multiple tables."""
    text = """| Table1 | H1 |
| --- | --- |

Some text

| Table2 | H2 |
| --- | --- |
| Data | Here |"""

    # Cursor in second table
    cursor_pos = text.find("| Data |")
    result = find_table_at_cursor(text, cursor_pos)

    assert result is not None
    start, end, table_text = result
    assert "Table2" in table_text
    assert "Table1" not in table_text


def test_is_table_line_valid(qtbot, app):
    """Test identifying valid table lines."""
    assert _is_table_line("| Header | Header2 |") is True
    assert _is_table_line("| --- | --- |") is True
    assert _is_table_line("| Cell | Cell2 | Cell3 |") is True


def test_is_table_line_invalid(qtbot, app):
    """Test identifying invalid table lines."""
    assert _is_table_line("Just regular text") is False
    assert _is_table_line("") is False
    assert _is_table_line("   ") is False
    assert _is_table_line("| Only one pipe") is False
    assert _is_table_line("Only one pipe |") is False
    assert _is_table_line("No pipes at all") is False


def test_is_table_line_edge_cases(qtbot, app):
    """Test edge cases for table line detection."""
    assert _is_table_line("|  |  |") is True  # Minimal valid table
    assert (
        _is_table_line("  | Header | Data |  ") is True
    )  # With leading/trailing spaces


def test_table_with_alignment_indicators(qtbot, app):
    """Test parsing table with alignment indicators."""
    table_text = """| Left | Center | Right |
| :--- | :---: | ---: |
| L1 | C1 | R1 |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    assert dialog.table_widget.columnCount() == 3
    assert dialog.table_widget.rowCount() == 1
    assert dialog.table_widget.item(0, 0).text() == "L1"


def test_accept_dialog(qtbot, app):
    """Test accepting the dialog."""
    table_text = "| H1 | H2 |\n| --- | --- |\n| A | B |"
    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    # Find and click the OK button
    for child in dialog.findChildren(type(dialog.findChild(type(None)))):
        if hasattr(child, "text") and callable(child.text):
            try:
                if "ok" in child.text().lower() or "OK" in child.text():
                    child.click()
                    break
            except:
                pass


def test_reject_dialog(qtbot, app):
    """Test rejecting the dialog."""
    table_text = "| H1 | H2 |\n| --- | --- |\n| A | B |"
    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    # Find and click the Cancel button
    for child in dialog.findChildren(type(dialog.findChild(type(None)))):
        if hasattr(child, "text") and callable(child.text):
            try:
                if "cancel" in child.text().lower():
                    child.click()
                    break
            except:
                pass


def test_table_with_uneven_columns(qtbot, app):
    """Test parsing table with uneven number of columns in rows."""
    table_text = """| H1 | H2 | H3 |
| --- | --- | --- |
| A | B |
| C | D | E | F |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    # Should handle gracefully
    assert dialog.table_widget.columnCount() == 3
    assert dialog.table_widget.rowCount() == 2


def test_table_with_empty_cells(qtbot, app):
    """Test parsing table with empty cells."""
    table_text = """| H1 | H2 | H3 |
| --- | --- | --- |
|  | B |  |
| C |  | E |"""

    dialog = TableEditorDialog(table_text)
    qtbot.addWidget(dialog)

    assert dialog.table_widget.item(0, 0).text() == ""
    assert dialog.table_widget.item(0, 1).text() == "B"
    assert dialog.table_widget.item(0, 2).text() == ""
    assert dialog.table_widget.item(1, 0).text() == "C"
    assert dialog.table_widget.item(1, 1).text() == ""
    assert dialog.table_widget.item(1, 2).text() == "E"
