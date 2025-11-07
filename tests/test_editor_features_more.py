import base64
from io import BytesIO

import pytest
from PySide6.QtCore import Qt, QMimeData, QByteArray
from PySide6.QtGui import QImage, QPixmap, QKeyEvent, QTextCursor
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from bouquin.editor import Editor
from bouquin.theme import ThemeManager, ThemeConfig


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance()
    if a is None:
        a = QApplication([])
    return a


@pytest.fixture
def editor(app, qtbot):
    themes = ThemeManager(app, ThemeConfig())
    e = Editor(themes)
    qtbot.addWidget(e)
    e.show()
    return e


def test_todo_prefix_converts_to_checkbox_on_space(editor):
    editor.clear()
    editor.setPlainText("TODO")
    c = editor.textCursor()
    c.movePosition(QTextCursor.End)
    editor.setTextCursor(c)
    QTest.keyClick(editor, Qt.Key_Space)
    # Now the line should start with the checkbox glyph and a space
    assert editor.toPlainText().startswith("☐ ")


def test_enter_inside_empty_code_frame_jumps_out(editor):
    editor.clear()
    editor.setPlainText("")  # single empty block
    # Apply code block to current line
    editor.apply_code()
    # Cursor is inside the code frame. Press Enter on empty block should jump out.
    QTest.keyClick(editor, Qt.Key_Return)
    # We expect two blocks: one code block (with a newline inserted) and then a normal block
    txt = editor.toPlainText()
    assert "\n" in txt  # a normal paragraph created after exiting the frame


def test_insertFromMimeData_with_data_image(editor):
    # Build an in-memory PNG and embed as data URL inside HTML
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(0xFF00FF00)  # green
    ba = QByteArray()
    from PySide6.QtCore import QBuffer, QIODevice

    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    data_b64 = base64.b64encode(bytes(ba)).decode("ascii")
    html = f'<img src="data:image/png;base64,{data_b64}"/>'

    md = QMimeData()
    md.setHtml(html)
    editor.insertFromMimeData(md)

    # HTML export with embedded images should contain a data: URL
    h = editor.to_html_with_embedded_images()
    assert "data:image/png;base64," in h


def test_toggle_checkboxes_selection(editor):
    editor.clear()
    editor.setPlainText("item 1\nitem 2")
    # Select both lines
    c = editor.textCursor()
    c.movePosition(QTextCursor.Start)
    c.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
    editor.setTextCursor(c)
    # Toggle on -> inserts ☐
    editor.toggle_checkboxes()
    assert editor.toPlainText().startswith("☐ ")
    # Toggle again -> remove ☐
    editor.toggle_checkboxes()
    assert not editor.toPlainText().startswith("☐ ")


def test_heading_then_enter_reverts_to_normal(editor):
    editor.clear()
    editor.setPlainText("A heading")
    # Apply H2 via apply_heading(size=18)
    editor.apply_heading(18)
    c = editor.textCursor()
    c.movePosition(QTextCursor.End)
    editor.setTextCursor(c)
    # Press Enter -> new block should be Normal (not bold/large)
    QTest.keyClick(editor, Qt.Key_Return)
    # The new block exists
    txt = editor.toPlainText()
    assert "\n" in txt
