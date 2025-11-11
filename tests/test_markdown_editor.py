import pytest

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QColor, QKeyEvent, QTextCursor
from bouquin.markdown_editor import MarkdownEditor
from bouquin.theme import ThemeManager, ThemeConfig, Theme


def text(editor) -> str:
    return editor.toPlainText()


def lines_keep(editor):
    """Split preserving a trailing empty line if the text ends with '\\n'."""
    return text(editor).split("\n")


def press_backtick(qtbot, widget, n=1):
    """Send physical backtick key events (avoid IME/dead-key issues)."""
    for _ in range(n):
        qtbot.keyClick(widget, Qt.Key_QuoteLeft)


@pytest.fixture
def editor(app, qtbot):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    ed = MarkdownEditor(themes)
    qtbot.addWidget(ed)
    ed.show()
    qtbot.waitExposed(ed)
    ed.setFocus()
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


@pytest.mark.gui
def test_triple_backtick_autoexpands(editor, qtbot):
    editor.from_markdown("")
    press_backtick(qtbot, editor, 2)
    press_backtick(qtbot, editor, 1)  # triggers expansion
    qtbot.wait(0)

    t = text(editor)
    assert t.count("```") == 2
    assert t.startswith("```\n\n```")
    assert t.endswith("\n")
    # caret is on the blank line inside the block
    assert editor.textCursor().blockNumber() == 1
    assert lines_keep(editor)[1] == ""


@pytest.mark.gui
def test_toolbar_inserts_block_on_own_lines(editor, qtbot):
    editor.from_markdown("hello")
    editor.moveCursor(QTextCursor.End)
    editor.apply_code()  # </> action
    qtbot.wait(0)

    t = text(editor)
    assert "hello```" not in t  # never inline
    assert t.startswith("hello\n```")
    assert t.endswith("```\n")
    # caret inside block (blank line)
    assert editor.textCursor().blockNumber() == 2
    assert lines_keep(editor)[2] == ""


@pytest.mark.gui
def test_toolbar_inside_block_does_not_insert_inline_fences(editor, qtbot):
    editor.from_markdown("")
    editor.apply_code()  # create a block (caret now on blank line inside)
    qtbot.wait(0)

    pos_before = editor.textCursor().position()
    t_before = text(editor)

    editor.apply_code()  # pressing </> inside should be a no-op
    qtbot.wait(0)

    assert text(editor) == t_before
    assert editor.textCursor().position() == pos_before


@pytest.mark.gui
def test_toolbar_on_opening_fence_jumps_inside(editor, qtbot):
    editor.from_markdown("")
    editor.apply_code()
    qtbot.wait(0)

    # Go to opening fence (line 0)
    editor.moveCursor(QTextCursor.Start)
    editor.apply_code()  # should jump inside the block
    qtbot.wait(0)

    assert editor.textCursor().blockNumber() == 1
    assert lines_keep(editor)[1] == ""


@pytest.mark.gui
def test_toolbar_on_closing_fence_jumps_out(editor, qtbot):
    editor.from_markdown("")
    editor.apply_code()
    qtbot.wait(0)

    # Go to closing fence line (template: 0 fence, 1 blank, 2 fence, 3 blank-after)
    editor.moveCursor(QTextCursor.End)  # blank-after
    editor.moveCursor(QTextCursor.Up)  # closing fence
    editor.moveCursor(QTextCursor.StartOfLine)

    editor.apply_code()  # jump to the line after the fence
    qtbot.wait(0)

    # Now on the blank line after the block
    assert editor.textCursor().block().text() == ""
    assert editor.textCursor().block().previous().text().strip() == "```"


@pytest.mark.gui
def test_down_escapes_from_last_code_line(editor, qtbot):
    editor.from_markdown("```\nLINE\n```\n")
    # Put caret at end of "LINE"
    editor.moveCursor(QTextCursor.Start)
    editor.moveCursor(QTextCursor.Down)  # "LINE"
    editor.moveCursor(QTextCursor.EndOfLine)

    qtbot.keyPress(editor, Qt.Key_Down)  # hop after closing fence
    qtbot.wait(0)

    # caret now on the blank line after the fence
    assert editor.textCursor().block().text() == ""
    assert editor.textCursor().block().previous().text().strip() == "```"


@pytest.mark.gui
def test_down_on_closing_fence_at_eof_creates_line(editor, qtbot):
    editor.from_markdown("```\ncode\n```")  # no trailing newline
    # caret on closing fence line
    editor.moveCursor(QTextCursor.End)
    editor.moveCursor(QTextCursor.StartOfLine)

    qtbot.keyPress(editor, Qt.Key_Down)  # should append newline and move there
    qtbot.wait(0)

    # Do NOT use splitlines() here—preserve trailing blank line
    assert text(editor).endswith("\n")
    assert editor.textCursor().block().text() == ""  # on the new blank line
    assert editor.textCursor().block().previous().text().strip() == "```"


@pytest.mark.gui
def test_no_orphan_two_backticks_lines_after_edits(editor, qtbot):
    editor.from_markdown("")
    # create a block via typing
    press_backtick(qtbot, editor, 3)
    qtbot.keyClicks(editor, "x")
    qtbot.keyPress(editor, Qt.Key_Down)  # escape
    editor.apply_code()  # add second block via toolbar
    qtbot.wait(0)

    # ensure there are no stray "``" lines
    assert not any(ln.strip() == "``" for ln in lines_keep(editor))
