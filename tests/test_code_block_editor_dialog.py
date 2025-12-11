from bouquin import strings
from bouquin.code_block_editor_dialog import (
    CodeBlockEditorDialog,
    CodeEditorWithLineNumbers,
)
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QFont, QPaintEvent
from PySide6.QtWidgets import QPushButton


def _find_button_by_text(widget, text):
    for btn in widget.findChildren(QPushButton):
        if text.lower() in btn.text().lower():
            return btn
    return None


def test_code_block_dialog_delete_flow(qtbot):
    dlg = CodeBlockEditorDialog("print(1)", "python", allow_delete=True)
    qtbot.addWidget(dlg)
    delete_txt = strings._("delete_code_block")
    delete_btn = _find_button_by_text(dlg, delete_txt)
    assert delete_btn is not None
    assert not dlg.was_deleted()
    with qtbot.waitSignal(dlg.finished, timeout=2000):
        delete_btn.click()
    assert dlg.was_deleted()


def test_code_block_dialog_language_and_code(qtbot):
    dlg = CodeBlockEditorDialog("x = 1", "not-a-lang", allow_delete=False)
    qtbot.addWidget(dlg)
    delete_txt = strings._("delete_code_block")
    assert _find_button_by_text(dlg, delete_txt) is None
    assert dlg.code() == "x = 1"
    assert dlg.language() is None


def test_line_number_area_size_hint(qtbot, app):
    """Test _LineNumberArea.sizeHint() method."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)

    line_area = editor._line_number_area
    size_hint = line_area.sizeHint()

    # Should return a QSize with width from editor
    assert isinstance(size_hint, QSize)
    assert size_hint.width() > 0
    assert size_hint.height() == 0


def test_line_number_area_paint_event(qtbot, app):
    """Test _LineNumberArea.paintEvent() method."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)
    editor.setPlainText("Line 1\nLine 2\nLine 3")
    editor.show()

    # Trigger a paint event on the line number area
    line_area = editor._line_number_area
    paint_event = QPaintEvent(QRect(0, 0, line_area.width(), line_area.height()))
    line_area.paintEvent(paint_event)

    # Should not crash


def test_line_number_font_pixel_size_fallback(qtbot, app):
    """Test _line_number_font() with pixel-sized font."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)

    # Set a pixel-sized font (pointSize will be -1)
    font = QFont()
    font.setPixelSize(14)
    editor.setFont(font)

    # Get line number font - should use the fallback
    line_font = editor._line_number_font()

    # Should have calculated a size
    assert line_font.pointSizeF() > 0 or line_font.pixelSize() > 0


def test_code_editor_resize_event(qtbot, app):
    """Test CodeEditorWithLineNumbers.resizeEvent() method."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)
    editor.show()

    # Resize the editor
    editor.resize(400, 300)

    # Line number area should be repositioned
    line_area = editor._line_number_area
    assert line_area.geometry().width() > 0
    assert line_area.geometry().height() == editor.contentsRect().height()


def test_code_editor_update_with_scroll(qtbot, app):
    """Test _update_line_number_area with dy (scroll) parameter."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)

    # Add enough text to enable scrolling
    text = "\n".join([f"Line {i}" for i in range(100)])
    editor.setPlainText(text)
    editor.show()

    # Trigger update with scroll offset
    rect = QRect(0, 0, 100, 100)
    editor._update_line_number_area(rect, dy=10)

    # Should not crash


def test_code_editor_update_without_scroll(qtbot, app):
    """Test _update_line_number_area without scroll (dy=0)."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)
    editor.setPlainText("Line 1\nLine 2")
    editor.show()

    # Trigger update without scroll
    rect = QRect(0, 0, 100, 100)
    editor._update_line_number_area(rect, dy=0)

    # Should not crash


def test_code_editor_update_contains_viewport(qtbot, app):
    """Test _update_line_number_area when rect contains viewport."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)
    editor.setPlainText("Test")
    editor.show()

    # Trigger update with rect that contains viewport
    viewport_rect = editor.viewport().rect()
    editor._update_line_number_area(viewport_rect, dy=0)

    # Should trigger width update (covers line 82)


def test_line_number_area_paint_with_multiple_blocks(qtbot, app):
    """Test line_number_area_paint_event with multiple text blocks."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)

    # Add multiple lines
    text = "\n".join([f"Line {i}" for i in range(20)])
    editor.setPlainText(text)
    editor.show()

    # Force a paint event
    line_area = editor._line_number_area
    rect = QRect(0, 0, line_area.width(), line_area.height())
    paint_event = QPaintEvent(rect)

    # This should exercise the painting loop
    editor.line_number_area_paint_event(paint_event)

    # Should not crash


def test_line_number_area_paint_with_long_file(qtbot, app):
    """Test line_number_area_paint_event with many lines."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)

    # Add 1000+ lines to test digit calculation and painting
    text = "\n".join([f"Line {i}" for i in range(1000)])
    editor.setPlainText(text)
    editor.show()

    # Trigger paint event
    line_area = editor._line_number_area
    paint_event = QPaintEvent(line_area.rect())
    editor.line_number_area_paint_event(paint_event)

    # Line number width should accommodate 4 digits
    width = editor.line_number_area_width()
    assert width > 30  # Should be wider for 4-digit numbers


def test_code_block_editor_dialog_with_delete(qtbot, app):
    """Test CodeBlockEditorDialog with allow_delete=True."""
    dialog = CodeBlockEditorDialog("print('hello')", "python", allow_delete=True)
    qtbot.addWidget(dialog)

    # Should have delete button functionality
    assert hasattr(dialog, "_delete_requested")
    assert dialog._delete_requested is False

    # Simulate delete click
    dialog._on_delete_clicked()

    assert dialog._delete_requested is True
    assert dialog.was_deleted() is True


def test_code_block_editor_dialog_without_delete(qtbot, app):
    """Test CodeBlockEditorDialog with allow_delete=False."""
    dialog = CodeBlockEditorDialog("print('hello')", "python", allow_delete=False)
    qtbot.addWidget(dialog)

    # Should not have been deleted
    assert dialog.was_deleted() is False


def test_code_block_editor_dialog_language_selection(qtbot, app):
    """Test language selection in dialog."""
    dialog = CodeBlockEditorDialog("test", "javascript")
    qtbot.addWidget(dialog)

    # Should have selected javascript
    assert dialog.language() == "javascript"

    # Change language
    dialog._lang_combo.setCurrentText("python")
    assert dialog.language() == "python"

    # Empty language
    dialog._lang_combo.setCurrentText("")
    assert dialog.language() is None


def test_code_block_editor_dialog_code_retrieval(qtbot, app):
    """Test getting code from dialog."""
    original_code = "def foo():\n    pass"
    dialog = CodeBlockEditorDialog(original_code, None)
    qtbot.addWidget(dialog)

    # Should return the code
    assert dialog.code() == original_code

    # Modify code
    new_code = "def bar():\n    return 42"
    dialog._code_edit.setPlainText(new_code)
    assert dialog.code() == new_code


def test_code_editor_with_empty_text(qtbot, app):
    """Test editor with no text."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)
    editor.show()

    # Should still paint line numbers
    line_area = editor._line_number_area
    paint_event = QPaintEvent(line_area.rect())
    editor.line_number_area_paint_event(paint_event)

    # Should not crash


def test_code_editor_block_count_changed(qtbot, app):
    """Test that block count changes trigger width updates."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)

    initial_width = editor.line_number_area_width()

    # Add lots of lines (should require more digits)
    text = "\n".join([f"Line {i}" for i in range(1000)])
    editor.setPlainText(text)

    new_width = editor.line_number_area_width()

    # Width should increase for more digits
    assert new_width > initial_width


def test_code_editor_cursor_position_changed(qtbot, app):
    """Test that cursor position changes update line number area."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)
    editor.setPlainText("Line 1\nLine 2\nLine 3")
    editor.show()

    # Move cursor
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)

    # Should trigger line number area update (via signal connection)
    # Just verify it doesn't crash


def test_line_number_area_width_calculation(qtbot, app):
    """Test line number area width calculation with various block counts."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)

    # Test with 1 line (should use minimum 2 digits)
    editor.setPlainText("One line")
    width_1 = editor.line_number_area_width()
    assert width_1 > 0

    # Test with 10 lines (2 digits)
    editor.setPlainText("\n".join(["Line"] * 10))
    width_10 = editor.line_number_area_width()
    assert width_10 >= width_1

    # Test with 100 lines (3 digits)
    editor.setPlainText("\n".join(["Line"] * 100))
    width_100 = editor.line_number_area_width()
    assert width_100 > width_10


def test_code_editor_viewport_margins(qtbot, app):
    """Test that viewport margins are set correctly."""
    editor = CodeEditorWithLineNumbers()
    qtbot.addWidget(editor)
    editor.setPlainText("Test")
    editor.show()

    # Left margin should equal line number area width
    margins = editor.viewportMargins()
    line_width = editor.line_number_area_width()

    assert margins.left() == line_width
    assert margins.top() == 0
    assert margins.right() == 0
    assert margins.bottom() == 0
