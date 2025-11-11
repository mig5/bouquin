import pytest

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QColor, QKeyEvent, QTextCursor
from bouquin.markdown_editor import MarkdownEditor
from bouquin.theme import ThemeManager, ThemeConfig, Theme


@pytest.fixture
def editor(app, qtbot):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    ed = MarkdownEditor(themes)
    qtbot.addWidget(ed)
    ed.show()
    return ed


def test_from_and_to_markdown_roundtrip(editor):
    md = "# Title\n\nThis is **bold** and _italic_ and ~~strike~~.\n\n- [ ] task\n- [x] done\n\n```\ncode\n```"
    editor.from_markdown(md)
    out = editor.to_markdown()
    assert "Title" in out and "task" in out and "code" in out


def test_apply_styles_and_headings(editor, qtbot):
    editor.from_markdown("hello world")
    editor.selectAll()
    editor.apply_weight()
    editor.apply_italic()
    editor.apply_strikethrough()
    editor.apply_heading(24)
    md = editor.to_markdown()
    assert "**" in md and "*~~~~*" in md


def test_toggle_lists_and_checkboxes(editor):
    editor.from_markdown("item one\nitem two\n")
    editor.toggle_bullets()
    assert "- " in editor.to_markdown()
    editor.toggle_numbers()
    assert "1. " in editor.to_markdown()
    editor.toggle_checkboxes()
    md = editor.to_markdown()
    assert "- [ ]" in md or "- [x]" in md


def test_insert_image_from_path(editor, tmp_path):
    img = tmp_path / "pic.png"
    qimg = QImage(2, 2, QImage.Format_RGBA8888)
    qimg.fill(QColor(255, 0, 0))
    assert qimg.save(str(img))  # ensure a valid PNG on disk

    editor.insert_image_from_path(img)
    md = editor.to_markdown()
    # Images are saved as base64 data URIs in markdown
    assert "data:image/image/png;base64" in md


def test_apply_code_inline(editor):
    editor.from_markdown("alpha beta")
    editor.selectAll()
    editor.apply_code()
    md = editor.to_markdown()
    assert ("`" in md) or ("```" in md)


@pytest.mark.gui
def test_auto_close_code_fence(editor, qtbot):
    # Place caret at start and type exactly `` then ` to trigger expansion
    editor.setPlainText("")
    qtbot.keyClicks(editor, "``")
    qtbot.keyClicks(editor, "`")  # third backtick triggers fence insertion
    txt = editor.toPlainText()
    assert "```" in txt and txt.count("```") >= 2


@pytest.mark.gui
def test_checkbox_toggle_by_click(editor, qtbot):
    # Load a markdown checkbox
    editor.from_markdown("- [ ] task here")
    # Verify display token present
    display = editor.toPlainText()
    assert "☐" in display

    # Click on the first character region to toggle
    c = editor.textCursor()
    from PySide6.QtGui import QTextCursor

    c.movePosition(QTextCursor.StartOfBlock)
    editor.setTextCursor(c)
    r = editor.cursorRect()
    center = r.center()
    # Send click slightly right to land within checkbox icon region
    pos = QPoint(r.left() + 2, center.y())
    qtbot.mouseClick(editor.viewport(), Qt.LeftButton, pos=pos)

    # Should have toggled to checked icon
    display2 = editor.toPlainText()
    assert "☑" in display2


@pytest.mark.gui
def test_apply_heading_levels(editor, qtbot):
    editor.setPlainText("hello")
    editor.selectAll()
    # H2
    editor.apply_heading(18)
    assert editor.toPlainText().startswith("## ")
    # H3
    editor.selectAll()
    editor.apply_heading(14)
    assert editor.toPlainText().startswith("### ")
    # Normal (no heading)
    editor.selectAll()
    editor.apply_heading(12)
    assert not editor.toPlainText().startswith("#")


@pytest.mark.gui
def test_enter_on_nonempty_list_continues(qtbot, editor):
    qtbot.addWidget(editor)
    editor.show()
    editor.from_markdown("- item")
    c = editor.textCursor()
    c.movePosition(QTextCursor.End)
    editor.setTextCursor(c)

    ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\n")
    editor.keyPressEvent(ev)
    txt = editor.toPlainText()
    assert "\n- " in txt


@pytest.mark.gui
def test_enter_on_empty_list_marks_empty(qtbot, editor):
    qtbot.addWidget(editor)
    editor.show()
    editor.from_markdown("- ")
    c = editor.textCursor()
    c.movePosition(QTextCursor.End)
    editor.setTextCursor(c)

    ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\n")
    editor.keyPressEvent(ev)
    assert editor.toPlainText().startswith("- \n")
