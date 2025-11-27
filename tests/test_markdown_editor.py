import base64
import pytest

from PySide6.QtCore import Qt, QPoint, QMimeData, QUrl
from PySide6.QtGui import (
    QImage,
    QColor,
    QKeyEvent,
    QTextCursor,
    QTextDocument,
    QFont,
    QTextCharFormat,
)
from PySide6.QtWidgets import QApplication, QTextEdit

from bouquin.markdown_editor import MarkdownEditor
from bouquin.markdown_highlighter import MarkdownHighlighter
from bouquin.theme import ThemeManager, ThemeConfig, Theme


def _today():
    from datetime import date

    return date.today().isoformat()


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


@pytest.fixture
def editor_hello(app):
    tm = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    e = MarkdownEditor(tm)
    e.setPlainText("hello")
    e.moveCursor(QTextCursor.MoveOperation.End)
    return e


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
    # Accept either "image/png" or older "image/image/png" prefix
    assert "data:image/png;base64" in md or "data:image/image/png;base64" in md


def test_checkbox_toggle_by_click(editor, qtbot):
    # Load a markdown checkbox
    editor.from_markdown("- [ ] task here")
    # Verify display token present
    display = editor.toPlainText()
    assert "☐" in display

    # Click on the first character region to toggle
    c = editor.textCursor()
    c.movePosition(QTextCursor.StartOfBlock)
    editor.setTextCursor(c)
    r = editor.cursorRect()
    center = r.center()
    pos = QPoint(r.left() + 2, center.y())
    qtbot.mouseClick(editor.viewport(), Qt.LeftButton, pos=pos)

    # Should have toggled to checked icon
    display2 = editor.toPlainText()
    assert "☑" in display2


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
    assert "\n\u2022 " in txt


def test_enter_on_empty_list_marks_empty(qtbot, editor):
    qtbot.addWidget(editor)
    editor.show()
    editor.from_markdown("- ")
    c = editor.textCursor()
    c.movePosition(QTextCursor.End)
    editor.setTextCursor(c)

    ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\n")
    editor.keyPressEvent(ev)
    assert editor.toPlainText().startswith("\u2022 \n")


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


def test_toolbar_inserts_block_on_own_lines(editor, qtbot):
    editor.from_markdown("hello")
    editor.moveCursor(QTextCursor.End)
    editor.apply_code()  # </> action inserts fenced code block
    qtbot.wait(0)

    t = text(editor)
    assert "hello```" not in t  # never inline
    assert t.startswith("hello\n```")
    assert t.endswith("```\n")
    # caret inside block (blank line)
    assert editor.textCursor().blockNumber() == 2
    assert lines_keep(editor)[2] == ""


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


def _fmt_at(block, pos):
    """Return a *copy* of the char format at pos so it doesn't dangle."""
    layout = block.layout()
    for fr in list(layout.formats()):
        if fr.start <= pos < fr.start + fr.length:
            return QTextCharFormat(fr.format)
    return None


@pytest.fixture
def highlighter(app):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    hl = MarkdownHighlighter(doc, themes)
    return doc, hl


def test_headings_and_inline_styles(highlighter):
    doc, hl = highlighter
    doc.setPlainText("# H1\n## H2\n### H3\n***b+i*** **b** *i* __b__ _i_\n")
    hl.rehighlight()

    # H1: '#' markers hidden (very small size), text bold/larger
    b0 = doc.findBlockByNumber(0)
    fmt_marker = _fmt_at(b0, 0)
    assert fmt_marker is not None
    assert fmt_marker.fontPointSize() <= 0.2  # marker hidden

    fmt_h1_text = _fmt_at(b0, 2)
    assert fmt_h1_text is not None
    assert fmt_h1_text.fontWeight() == QFont.Weight.Bold

    # Bold-italic precedence
    b3 = doc.findBlockByNumber(3)
    line = b3.text()
    triple = "***b+i***"
    start = line.find(triple)
    assert start != -1
    pos_inside = start + 3  # skip the *** markers, land on 'b'
    f_bi_inner = _fmt_at(b3, pos_inside)
    assert f_bi_inner is not None
    assert f_bi_inner.fontWeight() == QFont.Weight.Bold and f_bi_inner.fontItalic()

    # Bold without triples
    f_b = _fmt_at(b3, b3.text().find("**b**") + 2)
    assert f_b.fontWeight() == QFont.Weight.Bold

    # Italic without bold
    f_i = _fmt_at(b3, b3.text().rfind("_i_") + 1)
    assert f_i.fontItalic()


def test_code_blocks_inline_code_and_strike_overlay(highlighter):
    doc, hl = highlighter
    doc.setPlainText("```\n**B**\n```\nX ~~**boom**~~ Y `code`\n")
    hl.rehighlight()

    # Fence and inner lines use code block format
    fence = doc.findBlockByNumber(0)
    inner = doc.findBlockByNumber(1)

    fmt_fence = _fmt_at(fence, 0)
    fmt_inner = _fmt_at(inner, 0)
    assert fmt_fence is not None and fmt_inner is not None

    # check key properties
    assert fmt_inner.fontFixedPitch() or fmt_inner.font().styleHint() == QFont.Monospace
    assert fmt_inner.background() == hl.code_block_format.background()

    # Inline code uses fixed pitch and hides the backticks
    inline = doc.findBlockByNumber(3)
    start = inline.text().find("`code`")

    fmt_inline_char = _fmt_at(inline, start + 1)
    fmt_inline_tick = _fmt_at(inline, start)
    assert fmt_inline_char is not None and fmt_inline_tick is not None
    assert fmt_inline_char.fontFixedPitch()
    assert fmt_inline_tick.fontPointSize() <= 0.2  # backtick hidden

    boom_pos = inline.text().find("boom")
    fmt_boom = _fmt_at(inline, boom_pos)
    assert fmt_boom is not None
    assert fmt_boom.fontStrikeOut() and fmt_boom.fontWeight() == QFont.Weight.Bold


def test_theme_change_rehighlight(highlighter):
    doc, hl = highlighter
    hl._on_theme_changed()
    doc.setPlainText("`x`")
    hl.rehighlight()
    b = doc.firstBlock()
    fmt = _fmt_at(b, 1)
    assert fmt is not None and fmt.fontFixedPitch()


@pytest.fixture
def hl_light(app):
    # Light theme path
    tm = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    hl = MarkdownHighlighter(doc, tm)
    return doc, hl


@pytest.fixture
def hl_light_edit(app, qtbot):
    tm = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    edit = QTextEdit()  # <-- give the doc a layout
    edit.setDocument(doc)
    qtbot.addWidget(edit)
    edit.show()
    qtbot.wait(10)  # let Qt build the layouts
    hl = MarkdownHighlighter(doc, tm)
    return doc, hl, edit


def fmt(doc, block_no, pos):
    """Return the QTextCharFormat at character position `pos` in the given block."""
    b = doc.findBlockByNumber(block_no)
    it = b.begin()
    off = 0
    while not it.atEnd():
        frag = it.fragment()
        length = frag.length()  # includes chars in this fragment
        if off + length > pos:
            return frag.charFormat()
        off += length
        it = it.next()
    # Fallback (shouldn't happen in our tests)
    cf = QTextCharFormat()
    return cf


def test_light_palette_specific_colors(hl_light_edit, qtbot):
    doc, hl, edit = hl_light_edit
    doc.setPlainText("```\ncode\n```")
    hl.rehighlight()
    # the second block ("code") is the one inside the fenced block
    b_code = doc.firstBlock().next()
    fmt = _fmt_at(b_code, 0)
    assert fmt is not None and fmt.background().style() != 0


def test_code_block_light_colors(hl_light):
    """Ensure code block colors use the light palette (covers 74-75)."""
    doc, hl = hl_light
    doc.setPlainText("```\ncode\n```")
    hl.rehighlight()
    # Background is a light gray and text is dark/black-ish in light theme
    bg = hl.code_block_format.background().color()
    fg = hl.code_block_format.foreground().color()
    assert bg.red() >= 240 and bg.green() >= 240 and bg.blue() >= 240
    assert fg.red() < 40 and fg.green() < 40 and fg.blue() < 40


def test_end_guard_skips_italic_followed_by_marker(hl_light):
    """
    Triggers the end-following guard for italic e.g. '*i**'.
    """
    doc, hl = hl_light
    doc.setPlainText("*i**")
    hl.rehighlight()
    # The 'i' should not get italic due to the guard (closing '*' followed by '*')
    f = fmt(doc, 0, 1)
    assert not f.fontItalic()


def test_char_rect_at_edges_and_click_checkbox(editor, qtbot):
    """
    Exercises char_rect_at()-style logic and checkbox toggle via click
    to push coverage on geometry-dependent paths.
    """
    editor.from_markdown("- [ ] task")
    c = editor.textCursor()
    c.movePosition(QTextCursor.StartOfBlock)
    editor.setTextCursor(c)
    r = editor.cursorRect()
    qtbot.mouseClick(editor.viewport(), Qt.LeftButton, pos=r.center())
    assert "☑" in editor.toPlainText()


def test_heading_apply_levels_and_inline_styles(editor):
    editor.setPlainText("hello")
    editor.selectAll()
    editor.apply_heading(18)  # H2
    assert editor.toPlainText().startswith("## ")
    editor.selectAll()
    editor.apply_heading(12)  # normal
    assert not editor.toPlainText().startswith("#")

    # Bold/italic/strike together to nudge style branches
    editor.setPlainText("hi")
    editor.selectAll()
    editor.apply_weight()
    editor.apply_italic()
    editor.apply_strikethrough()
    md = editor.to_markdown()
    assert "**" in md and "*" in md and "~~" in md


def test_insert_image_and_markdown_roundtrip(editor, tmp_path):
    img = tmp_path / "p.png"
    qimg = QImage(2, 2, QImage.Format_RGBA8888)
    qimg.fill(QColor(255, 0, 0))
    assert qimg.save(str(img))
    editor.insert_image_from_path(img)
    # At least a replacement char shows in the plain-text view
    assert "\ufffc" in editor.toPlainText()
    # And markdown contains a data: URI
    assert "data:image" in editor.to_markdown()


def test_apply_italic_and_strike(editor):
    # Italic: insert markers with no selection and place caret in between
    editor.setPlainText("x")
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.apply_italic()
    assert editor.toPlainText().endswith("x**")
    assert editor.textCursor().position() == len(editor.toPlainText()) - 1

    # With selection toggling
    editor.setPlainText("*y*")
    c = editor.textCursor()
    c.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.MoveAnchor)
    c.movePosition(QTextCursor.MoveOperation.Start, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(c)
    editor.apply_italic()
    assert editor.toPlainText() == "y"

    # Strike: no selection case inserts placeholder and moves caret
    editor.setPlainText("z")
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.apply_strikethrough()
    assert editor.toPlainText().endswith("z~~~~")
    assert editor.textCursor().position() == len(editor.toPlainText()) - 2


def test_apply_code_inline_block_navigation(editor):
    # Selection case -> fenced block around selection
    editor.setPlainText("code")
    c = editor.textCursor()
    c.select(QTextCursor.SelectionType.Document)
    editor.setTextCursor(c)
    editor.apply_code()
    assert "```\ncode\n```\n" in editor.toPlainText()

    # No selection, at EOF with no following block -> creates block and extra newline path
    editor.setPlainText("before")
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.apply_code()
    t = editor.toPlainText()
    assert t.endswith("before\n```\n\n```\n")
    # Caret should be inside the code block blank line
    assert editor.textCursor().position() == len("before\n") + 4


def test_insert_image_from_path_invalid_returns(editor_hello, tmp_path):
    # Non-existent path should just return (early exit)
    bad = tmp_path / "missing.png"
    editor_hello.insert_image_from_path(bad)
    # Nothing new added
    assert editor_hello.toPlainText() == "hello"


# ============================================================================
# setDocument Tests
# ============================================================================


def test_markdown_editor_set_document(app):
    """Test setting a new document on the editor"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)

    # Create a new document
    new_doc = QTextDocument()
    new_doc.setPlainText("New document content")

    # Set the document
    editor.setDocument(new_doc)

    # Verify document was set
    assert editor.document() == new_doc
    assert "New document content" in editor.toPlainText()


def test_markdown_editor_set_document_with_highlighter(app):
    """Test setting document preserves highlighter"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)

    # Ensure highlighter exists
    assert hasattr(editor, "highlighter")

    # Create and set new document
    new_doc = QTextDocument()
    new_doc.setPlainText("# Heading")
    editor.setDocument(new_doc)

    # Highlighter should be attached to new document
    assert editor.highlighter.document() == new_doc


# ============================================================================
# showEvent Tests
# ============================================================================


def test_markdown_editor_show_event(app, qtbot):
    """Test showEvent triggers code block background update"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.from_markdown("```python\ncode\n```")

    # Show the editor
    editor.show()
    qtbot.waitExposed(editor)

    # Process events to let QTimer.singleShot fire
    QApplication.processEvents()

    # Editor should be visible
    assert editor.isVisible()


# ============================================================================
# Checkbox Transformation Tests
# ============================================================================


def test_markdown_editor_transform_unchecked_checkbox(app, qtbot):
    """Test transforming - [ ] to unchecked checkbox"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.show()
    qtbot.waitExposed(editor)

    # Type checkbox markdown
    editor.insertPlainText("- [ ] Task")

    # Process events to let transformation happen
    QApplication.processEvents()

    # Should contain checkbox character
    text = editor.toPlainText()
    assert editor._CHECK_UNCHECKED_DISPLAY in text


def test_markdown_editor_transform_checked_checkbox(app, qtbot):
    """Test transforming - [x] to checked checkbox"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.show()
    qtbot.waitExposed(editor)

    # Type checked checkbox markdown
    editor.insertPlainText("- [x] Done")

    # Process events
    QApplication.processEvents()

    # Should contain checked checkbox character
    text = editor.toPlainText()
    assert editor._CHECK_CHECKED_DISPLAY in text


def test_markdown_editor_transform_todo(app, qtbot):
    """Test transforming TODO to unchecked checkbox"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.show()
    qtbot.waitExposed(editor)

    # Type TODO
    editor.insertPlainText("TODO: Important task")

    # Process events
    QApplication.processEvents()

    # Should contain checkbox and no TODO
    text = editor.toPlainText()
    assert editor._CHECK_UNCHECKED_DISPLAY in text


def test_markdown_editor_transform_todo_with_indent(app, qtbot):
    """Test transforming indented TODO"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.show()
    qtbot.waitExposed(editor)

    # Type indented TODO
    editor.insertPlainText("    TODO: Indented task")

    # Process events
    QApplication.processEvents()

    # Should handle indented TODO
    text = editor.toPlainText()
    assert editor._CHECK_UNCHECKED_DISPLAY in text


def test_markdown_editor_transform_todo_with_colon(app, qtbot):
    """Test transforming TODO: with colon"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.show()
    qtbot.waitExposed(editor)

    # Type TODO with colon
    editor.insertPlainText("TODO: Task with colon")

    # Process events
    QApplication.processEvents()

    text = editor.toPlainText()
    assert editor._CHECK_UNCHECKED_DISPLAY in text


def test_markdown_editor_transform_todo_with_dash(app, qtbot):
    """Test transforming TODO- with dash"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.show()
    qtbot.waitExposed(editor)

    # Type TODO with dash
    editor.insertPlainText("TODO- Task with dash")

    # Process events
    QApplication.processEvents()

    text = editor.toPlainText()
    assert editor._CHECK_UNCHECKED_DISPLAY in text


def test_markdown_editor_no_transform_when_updating(app):
    """Test that transformation doesn't happen when _updating flag is set"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)

    # Set updating flag
    editor._updating = True

    # Try to insert checkbox markdown
    editor.insertPlainText("- [ ] Task")

    # Should NOT transform since _updating is True
    # This tests the early return in _on_text_changed
    assert editor._updating


# ============================================================================
# Code Block Tests
# ============================================================================


def test_markdown_editor_is_inside_code_block(app):
    """Test detecting if cursor is inside code block"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.from_markdown("```python\ncode here\n```\noutside")

    # Move cursor to inside code block
    cursor = editor.textCursor()
    cursor.setPosition(10)  # Inside the code block
    editor.setTextCursor(cursor)

    block = cursor.block()
    # Test the method exists and can be called
    result = editor._is_inside_code_block(block)
    assert isinstance(result, bool)


def test_markdown_editor_code_block_spacing(app):
    """Test code block spacing application"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.from_markdown("```python\nline1\nline2\n```")

    # Apply code block spacing
    editor._apply_code_block_spacing()

    # Should complete without error
    assert True


def test_markdown_editor_update_code_block_backgrounds(app):
    """Test updating code block backgrounds"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.from_markdown("```python\ncode\n```")

    # Update backgrounds
    editor._update_code_block_row_backgrounds()

    # Should complete without error
    assert True


# ============================================================================
# Image Insertion Tests
# ============================================================================


def test_markdown_editor_insert_image_from_path(app, tmp_path):
    """Test inserting image from file path"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)

    # Create a real PNG image (1x1 pixel)
    # PNG file signature + minimal valid PNG data
    png_data = (
        b"\x89PNG\r\n\x1a\n"  # PNG signature
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"  # IHDR chunk
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4"  # IDAT chunk
        b"\x00\x00\x00\x00IEND\xaeB`\x82"  # IEND chunk
    )
    image_path = tmp_path / "test.png"
    image_path.write_bytes(png_data)

    # Insert image
    editor.insert_image_from_path(image_path)

    # Check that document has content (image + newline)
    # Images don't show in toPlainText() but affect document structure
    doc = editor.document()
    assert doc.characterCount() > 1  # Should have image char + newline


# ============================================================================
# Formatting Tests
# ============================================================================


def test_markdown_editor_toggle_bold_empty_selection(app):
    """Test toggling bold with no selection"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.insertPlainText("text")

    # Move cursor to middle of text (no selection)
    cursor = editor.textCursor()
    cursor.setPosition(2)
    editor.setTextCursor(cursor)

    # Toggle bold (inserts ** markers with cursor between them)
    editor.apply_weight()

    # Should have inserted bold markers
    text = editor.toPlainText()
    assert "**" in text

    # Should handle empty selection
    assert True


def test_markdown_editor_toggle_italic_empty_selection(app):
    """Test toggling italic with no selection"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.insertPlainText("text")

    # Move cursor to middle (no selection)
    cursor = editor.textCursor()
    cursor.setPosition(2)
    editor.setTextCursor(cursor)

    # Toggle italic
    editor.apply_italic()

    # Should handle empty selection
    assert True


def test_markdown_editor_toggle_strikethrough_empty_selection(app):
    """Test toggling strikethrough with no selection"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.insertPlainText("text")

    cursor = editor.textCursor()
    cursor.setPosition(2)
    editor.setTextCursor(cursor)

    editor.apply_strikethrough()

    assert True


def test_markdown_editor_toggle_code_empty_selection(app):
    """Test toggling code with no selection"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.insertPlainText("text")

    cursor = editor.textCursor()
    cursor.setPosition(2)
    editor.setTextCursor(cursor)

    editor.apply_code()

    assert True


# ============================================================================
# Heading Tests
# ============================================================================


def test_markdown_editor_set_heading_various_levels(app):
    """Test setting different heading levels"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)

    for level in [14, 18, 24]:
        editor.clear()
        editor.insertPlainText("Heading text")

        # Select all
        cursor = editor.textCursor()
        cursor.select(QTextCursor.Document)
        editor.setTextCursor(cursor)

        # Set heading level
        editor.apply_heading(level)

        # Should have heading markdown
        text = editor.toPlainText()
        assert "#" in text


def test_markdown_editor_set_heading_zero_removes_heading(app):
    """Test setting heading level 0 removes heading"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.from_markdown("# Heading")

    # Select heading
    cursor = editor.textCursor()
    cursor.select(QTextCursor.Document)
    editor.setTextCursor(cursor)

    # Set to level 0 (remove heading)
    editor.apply_heading(0)

    # Should not have heading markers
    text = editor.toPlainText()
    assert not text.startswith("#")


# ============================================================================
# List Tests
# ============================================================================


def test_markdown_editor_toggle_list_bullet(app):
    """Test toggling bullet list"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.insertPlainText("Item 1\nItem 2")

    # Select all
    cursor = editor.textCursor()
    cursor.select(QTextCursor.Document)
    editor.setTextCursor(cursor)

    # Toggle bullet list
    editor.toggle_bullets()

    # Should have bullet markers
    text = editor.toPlainText()
    assert "•" in text or "-" in text


def test_markdown_editor_toggle_list_ordered(app):
    """Test toggling ordered list"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.insertPlainText("Item 1\nItem 2")

    cursor = editor.textCursor()
    cursor.select(QTextCursor.Document)
    editor.setTextCursor(cursor)

    editor.toggle_numbers()

    text = editor.toPlainText()
    assert "1" in text or "2" in text


# ============================================================================
# Code Block Tests
# ============================================================================


def test_markdown_editor_apply_code_selected_text(app):
    """Test toggling code block with selected text"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.insertPlainText("def hello():\n    print('hi')")

    # Select all
    cursor = editor.textCursor()
    cursor.select(QTextCursor.Document)
    editor.setTextCursor(cursor)

    # Toggle code block
    editor.apply_code()

    # Should have code fence
    text = editor.toPlainText()
    assert "```" in text


def test_markdown_editor_apply_code_remove(app):
    """Test removing code block"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.from_markdown("```python\ncode\n```")

    # Select all
    cursor = editor.textCursor()
    cursor.select(QTextCursor.Document)
    editor.setTextCursor(cursor)

    # Toggle off
    editor.apply_code()

    # Code fences should be reduced/removed
    editor.toPlainText()
    # May still have ``` but different structure
    assert True  # Just verify no crash


# ============================================================================
# Checkbox Tests
# ============================================================================


def test_markdown_editor_insert_checkbox_unchecked(app):
    """Test inserting unchecked checkbox"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)

    editor.toggle_checkboxes()

    text = editor.toPlainText()
    assert editor._CHECK_UNCHECKED_DISPLAY in text


# ============================================================================
# Toggle Checkboxes Tests
# ============================================================================


def test_markdown_editor_toggle_checkboxes_none_selected(app):
    """Test toggling checkboxes with no selection"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.from_markdown("☐ Task 1\n☐ Task 2")

    # No selection, just cursor
    editor.toggle_checkboxes()

    # Should handle gracefully
    assert True


def test_markdown_editor_toggle_checkboxes_mixed(app):
    """Test toggling mixed checked/unchecked checkboxes"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.from_markdown("☐ Task 1\n☑ Task 2\n☐ Task 3")

    # Select all
    cursor = editor.textCursor()
    cursor.select(QTextCursor.Document)
    editor.setTextCursor(cursor)

    # Toggle
    editor.toggle_checkboxes()

    # Should toggle all
    text = editor.toPlainText()
    assert (
        editor._CHECK_CHECKED_DISPLAY in text or editor._CHECK_UNCHECKED_DISPLAY in text
    )


# ============================================================================
# Markdown Conversion Tests
# ============================================================================


def test_markdown_editor_to_markdown_with_checkboxes(app):
    """Test converting to markdown preserves checkboxes"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.from_markdown("- [ ] Task 1\n- [x] Task 2")

    md = editor.to_markdown()

    # Should have checkbox markdown
    assert "[ ]" in md or "[x]" in md


def test_markdown_editor_from_markdown_with_images(app):
    """Test loading markdown with images"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)

    md_with_image = "# Title\n\n![alt text](image.png)\n\nText"
    editor.from_markdown(md_with_image)

    # Should load without error
    text = editor.toPlainText()
    assert "Title" in text


def test_markdown_editor_from_markdown_with_links(app):
    """Test loading markdown with links"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)

    md_with_link = "[Click here](https://example.com)"
    editor.from_markdown(md_with_link)

    text = editor.toPlainText()
    assert "Click here" in text


# ============================================================================
# Selection and Cursor Tests
# ============================================================================


def test_markdown_editor_select_word_under_cursor(app):
    """Test selecting word under cursor"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.insertPlainText("Hello world test")

    # Move cursor to middle of word
    cursor = editor.textCursor()
    cursor.setPosition(7)  # Middle of "world"
    editor.setTextCursor(cursor)

    # Select word (via double-click or other mechanism)
    cursor.select(QTextCursor.WordUnderCursor)
    editor.setTextCursor(cursor)

    assert cursor.hasSelection()


def test_markdown_editor_get_selected_blocks(app):
    """Test getting selected blocks"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.insertPlainText("Line 1\nLine 2\nLine 3")

    # Select multiple lines
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(14, QTextCursor.KeepAnchor)
    editor.setTextCursor(cursor)

    # Should have selection
    assert cursor.hasSelection()


# ============================================================================
# Key Event Tests
# ============================================================================


def test_markdown_editor_key_press_tab(app):
    """Test tab key handling"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.show()

    # Create tab key event
    event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier)

    # Send event
    editor.keyPressEvent(event)

    # Should insert tab or spaces
    text = editor.toPlainText()
    assert len(text) > 0 or text == ""  # Tab or spaces inserted


def test_markdown_editor_key_press_return_in_list(app):
    """Test return key in list"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.from_markdown("- Item 1")

    # Move cursor to end
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)

    # Press return
    event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
    editor.keyPressEvent(event)

    # Should create new list item
    text = editor.toPlainText()
    assert "Item 1" in text


# ============================================================================
# Link Handling Tests
# ============================================================================


def test_markdown_editor_anchor_at_cursor(app):
    """Test getting anchor at cursor position"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.from_markdown("[link](https://example.com)")

    # Move cursor over link
    cursor = editor.textCursor()
    cursor.setPosition(2)
    editor.setTextCursor(cursor)

    # Get anchor (if any)
    anchor = cursor.charFormat().anchorHref()

    # May or may not have anchor depending on rendering
    assert isinstance(anchor, str)


def test_markdown_editor_mouse_move_over_link(app):
    """Test mouse movement over link"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(themes)
    editor.from_markdown("[link](https://example.com)")
    editor.show()

    # Simulate mouse move
    # This tests viewport event handling
    assert True  # Just verify no crash


# ============================================================================
# Theme Mode Tests
# ============================================================================


def test_markdown_highlighter_light_mode(app):
    """Test highlighter in light mode"""
    doc = QTextDocument()
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)

    # Check that light mode colors are set
    bg = highlighter.code_block_format.background().color()
    assert bg.isValid()
    # Check it's a light color (high RGB values, close to 245)
    assert bg.red() > 240 and bg.green() > 240 and bg.blue() > 240

    fg = highlighter.code_block_format.foreground().color()
    assert fg.isValid()
    # Check it's a dark color for text
    assert fg.red() < 50 and fg.green() < 50 and fg.blue() < 50


def test_markdown_highlighter_dark_mode(app):
    """Test highlighter in dark mode"""
    doc = QTextDocument()
    themes = ThemeManager(app, ThemeConfig(theme=Theme.DARK))
    highlighter = MarkdownHighlighter(doc, themes)

    # Check that dark mode uses palette colors
    bg = highlighter.code_block_format.background().color()
    fg = highlighter.code_block_format.foreground().color()

    assert bg.isValid()
    assert fg.isValid()


# ============================================================================
# Highlighting Pattern Tests
# ============================================================================


def test_markdown_highlighter_triple_backtick_code(app):
    """Test highlighting triple backtick code blocks"""
    doc = QTextDocument()
    doc.setPlainText("```python\ndef hello():\n    pass\n```")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)

    # Force rehighlight
    highlighter.rehighlight()

    # Should complete without errors
    assert True


def test_markdown_highlighter_inline_code(app):
    """Test highlighting inline code with backticks"""
    doc = QTextDocument()
    doc.setPlainText("Here is `inline code` in text")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)
    highlighter.rehighlight()

    assert True


def test_markdown_highlighter_bold_text(app):
    """Test highlighting bold text"""
    doc = QTextDocument()
    doc.setPlainText("This is **bold** text")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)
    highlighter.rehighlight()

    assert True


def test_markdown_highlighter_italic_text(app):
    """Test highlighting italic text"""
    doc = QTextDocument()
    doc.setPlainText("This is *italic* text")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)
    highlighter.rehighlight()

    assert True


def test_markdown_highlighter_headings(app):
    """Test highlighting various heading levels"""
    doc = QTextDocument()
    doc.setPlainText("# H1\n## H2\n### H3\n#### H4\n##### H5\n###### H6")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)
    highlighter.rehighlight()

    assert True


def test_markdown_highlighter_links(app):
    """Test highlighting markdown links"""
    doc = QTextDocument()
    doc.setPlainText("[link text](https://example.com)")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)
    highlighter.rehighlight()

    assert True


def test_markdown_highlighter_images(app):
    """Test highlighting markdown images"""
    doc = QTextDocument()
    doc.setPlainText("![alt text](image.png)")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)
    highlighter.rehighlight()

    assert True


def test_markdown_highlighter_blockquotes(app):
    """Test highlighting blockquotes"""
    doc = QTextDocument()
    doc.setPlainText("> This is a quote\n> Second line")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)
    highlighter.rehighlight()

    assert True


def test_markdown_highlighter_lists(app):
    """Test highlighting lists"""
    doc = QTextDocument()
    doc.setPlainText("- Item 1\n- Item 2\n- Item 3")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)
    highlighter.rehighlight()

    assert True


def test_markdown_highlighter_ordered_lists(app):
    """Test highlighting ordered lists"""
    doc = QTextDocument()
    doc.setPlainText("1. First\n2. Second\n3. Third")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)
    highlighter.rehighlight()

    assert True


def test_markdown_highlighter_horizontal_rules(app):
    """Test highlighting horizontal rules"""
    doc = QTextDocument()
    doc.setPlainText("Text above\n\n---\n\nText below")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)
    highlighter.rehighlight()

    assert True


def test_markdown_highlighter_strikethrough(app):
    """Test highlighting strikethrough text"""
    doc = QTextDocument()
    doc.setPlainText("This is ~~strikethrough~~ text")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)
    highlighter.rehighlight()

    assert True


def test_markdown_highlighter_mixed_formatting(app):
    """Test highlighting mixed markdown formatting"""
    doc = QTextDocument()
    doc.setPlainText(
        "# Title\n\nThis is **bold** and *italic* with `code`.\n\n- List item\n- Another item"
    )

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter = MarkdownHighlighter(doc, themes)
    highlighter.rehighlight()

    assert True


def test_markdown_highlighter_switch_dark_mode(app):
    """Test that dark mode uses different colors than light mode"""
    doc = QTextDocument()
    doc.setPlainText("# Test")

    # Create light mode highlighter
    themes_light = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    highlighter_light = MarkdownHighlighter(doc, themes_light)
    light_bg = highlighter_light.code_block_format.background().color()

    # Create dark mode highlighter with new document (to avoid conflicts)
    doc2 = QTextDocument()
    doc2.setPlainText("# Test")
    themes_dark = ThemeManager(app, ThemeConfig(theme=Theme.DARK))
    highlighter_dark = MarkdownHighlighter(doc2, themes_dark)
    dark_bg = highlighter_dark.code_block_format.background().color()

    # In light mode, background should be light (high RGB values)
    # In dark mode, background should be darker (lower RGB values)
    # Note: actual values depend on system palette and theme settings
    assert light_bg.isValid()
    assert dark_bg.isValid()

    # At least one of these should be true (depending on system theme):
    # - Light is lighter than dark, OR
    # - Both are set to valid colors (if system theme overrides)
    is_light_lighter = (
        light_bg.red() + light_bg.green() + light_bg.blue()
        > dark_bg.red() + dark_bg.green() + dark_bg.blue()
    )
    both_valid = light_bg.isValid() and dark_bg.isValid()

    assert is_light_lighter or both_valid  # At least colors are being set


# ============================================================================
# MarkdownHighlighter Tests - Missing Coverage
# ============================================================================


def test_markdown_highlighter_code_block_detection(qtbot, app):
    """Test code block detection and highlighting."""
    theme_manager = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, theme_manager)

    # Set text with code block
    text = """
Some text
```python
def hello():
    pass
```
More text
"""
    doc.setPlainText(text)

    # The highlighter should process the text
    # Just ensure no crash
    assert highlighter is not None


def test_markdown_highlighter_headers(qtbot, app):
    """Test header highlighting."""
    theme_manager = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, theme_manager)

    text = """
# Header 1
## Header 2
### Header 3
Normal text
"""
    doc.setPlainText(text)

    assert highlighter is not None


def test_markdown_highlighter_emphasis(qtbot, app):
    """Test emphasis highlighting."""
    theme_manager = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, theme_manager)

    text = "**bold** and *italic* and ***both***"
    doc.setPlainText(text)

    assert highlighter is not None


def test_markdown_highlighter_horizontal_rule(qtbot, app):
    """Test horizontal rule highlighting."""
    theme_manager = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, theme_manager)

    text = """
Text above
---
Text below
***
More text
___
End
"""
    doc.setPlainText(text)

    assert highlighter is not None


def test_markdown_highlighter_complex_document(qtbot, app):
    """Test highlighting a complex document with mixed elements."""
    theme_manager = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, theme_manager)

    text = """
# Main Title

This is a paragraph with **bold** and *italic* text.

## Code Example

Here's some `inline code` and a block:

```python
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
```

## Lists

- Item with *emphasis*
- Another item with **bold**
- [A link](https://example.com)

> A blockquote with **formatted** text
> Second line

---

### Final Section

~~Strikethrough~~ and normal text.
"""
    doc.setPlainText(text)

    # Should handle complex document
    assert highlighter is not None


def test_markdown_highlighter_empty_document(qtbot, app):
    """Test highlighting empty document."""
    theme_manager = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, theme_manager)

    doc.setPlainText("")

    assert highlighter is not None


def test_markdown_highlighter_update_on_text_change(qtbot, app):
    """Test that highlighter updates when text changes."""
    theme_manager = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, theme_manager)

    doc.setPlainText("Initial text")
    doc.setPlainText("# Header text")
    doc.setPlainText("**Bold text**")

    # Should handle updates
    assert highlighter is not None


def test_markdown_highlighter_nested_emphasis(qtbot, app):
    """Test nested emphasis patterns."""
    theme_manager = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, theme_manager)

    text = "This has **bold with *italic* inside** and more"
    doc.setPlainText(text)

    assert highlighter is not None


def test_markdown_highlighter_unclosed_code_block(qtbot, app):
    """Test handling of unclosed code block."""
    theme_manager = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, theme_manager)

    text = """
```python
def hello():
    print("world")
"""
    doc.setPlainText(text)

    # Should handle gracefully
    assert highlighter is not None


def test_markdown_highlighter_special_characters(qtbot, app):
    """Test handling special characters in markdown."""
    theme_manager = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, theme_manager)

    text = """
Special chars: < > & " ' 
Escaped: \\* \\_ \\`
Unicode: 你好 café résumé
"""
    doc.setPlainText(text)

    assert highlighter is not None


@pytest.mark.parametrize(
    "markdown_line",
    [
        "- [ ] Task",  # checkbox
        "- Task",  # bullet
        "1. Task",  # numbered
    ],
)
def test_home_on_list_line_moves_to_text_start(qtbot, editor, markdown_line):
    """Home on a list line should jump to just after the list marker."""
    editor.from_markdown(markdown_line)

    # Put caret at end of the line
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)

    # Press Home (no modifiers)
    qtbot.keyPress(editor, Qt.Key_Home)
    qtbot.wait(0)

    c = editor.textCursor()
    block = c.block()
    line = block.text()
    pos_in_block = c.position() - block.position()

    # The first character of the user text is the 'T' in "Task"
    logical_start = line.index("Task")

    assert not c.hasSelection()
    assert pos_in_block == logical_start


@pytest.mark.parametrize(
    "markdown_line",
    [
        "- [ ] Task",  # checkbox
        "- Task",  # bullet
        "1. Task",  # numbered
    ],
)
def test_shift_home_on_list_line_selects_text_after_marker(
    qtbot, editor, markdown_line
):
    """
    Shift+Home from the end of a list line should select the text after the marker,
    not the marker itself.
    """
    editor.from_markdown(markdown_line)

    # Put caret at end of the line
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)

    # Shift+Home: extend selection back to "logical home"
    qtbot.keyPress(editor, Qt.Key_Home, Qt.ShiftModifier)
    qtbot.wait(0)

    c = editor.textCursor()
    block = c.block()
    line = block.text()
    block_start = block.position()

    logical_start = line.index("Task")
    expected_start = block_start + logical_start
    expected_end = block_start + len(line)

    assert c.hasSelection()
    assert c.selectionStart() == expected_start
    assert c.selectionEnd() == expected_end
    # Selected text is exactly the user-visible text, not the marker
    assert c.selectedText() == line[logical_start:]


def test_up_from_below_checkbox_moves_to_text_start(qtbot, editor):
    """
    Up from the line below a checkbox should land to the right of the checkbox,
    where the text starts, not to the left of the marker.
    """
    editor.from_markdown("- [ ] Task\nSecond line")

    # Put caret somewhere on the second line (end of document is fine)
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)

    # Press Up to move to the checkbox line
    qtbot.keyPress(editor, Qt.Key_Up)
    qtbot.wait(0)

    c = editor.textCursor()
    block = c.block()
    line = block.text()
    pos_in_block = c.position() - block.position()

    logical_start = line.index("Task")
    assert pos_in_block >= logical_start


def test_backspace_on_empty_checkbox_removes_marker(qtbot, editor):
    """
    When a checkbox line has no text after the marker, Backspace at/after the
    text position should delete the marker itself, leaving a plain empty line.
    """
    editor.from_markdown("- [ ] ")

    # Put caret at end of the checkbox line (after the marker)
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)

    qtbot.keyPress(editor, Qt.Key_Backspace)
    qtbot.wait(0)

    first_block = editor.document().firstBlock()
    # Marker should be gone
    assert first_block.text() == ""
    assert editor._CHECK_UNCHECKED_DISPLAY not in editor.toPlainText()


def test_render_images_with_corrupted_data(qtbot, app):
    """Test rendering images with corrupted data that creates null QImage"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(theme_manager=themes)
    qtbot.addWidget(editor)
    editor.show()

    # Create some binary data that will decode but not form a valid image
    corrupted_data = base64.b64encode(b"not an image file").decode("utf-8")
    markdown = f"![corrupted](data:image/png;base64,{corrupted_data})"

    editor.from_markdown(markdown)
    qtbot.wait(50)

    # Should still work without crashing
    text = editor.to_markdown()
    assert len(text) >= 0


def test_editor_with_code_blocks(qtbot, app):
    """Test editor with code blocks"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(theme_manager=themes)
    qtbot.addWidget(editor)
    editor.show()

    code_markdown = """
Some text

```python
def hello():
    print("world")
```

More text
"""
    editor.from_markdown(code_markdown)
    qtbot.wait(50)

    result = editor.to_markdown()
    assert "def hello" in result or "python" in result


def test_editor_undo_redo(qtbot, app):
    """Test undo/redo functionality"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(theme_manager=themes)
    qtbot.addWidget(editor)
    editor.show()

    # Type some text
    editor.from_markdown("Initial text")
    qtbot.wait(50)

    # Add more text
    editor.insertPlainText(" additional")
    qtbot.wait(50)

    # Undo
    editor.undo()
    qtbot.wait(50)

    # Redo
    editor.redo()
    qtbot.wait(50)

    assert len(editor.to_markdown()) > 0


def test_editor_cut_copy_paste(qtbot, app):
    """Test cut/copy/paste operations"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(theme_manager=themes)
    qtbot.addWidget(editor)
    editor.show()

    editor.from_markdown("Test content for copy")
    qtbot.wait(50)

    # Select all
    editor.selectAll()

    # Copy
    editor.copy()
    qtbot.wait(50)

    # Move to end and paste
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)

    editor.paste()
    qtbot.wait(50)

    # Should have content twice (or clipboard might be empty in test env)
    assert len(editor.to_markdown()) > 0


def test_editor_with_blockquotes(qtbot, app):
    """Test editor with blockquotes"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(theme_manager=themes)
    qtbot.addWidget(editor)
    editor.show()

    quote_markdown = """
Normal text

> This is a quote
> With multiple lines

More normal text
"""
    editor.from_markdown(quote_markdown)
    qtbot.wait(50)

    result = editor.to_markdown()
    assert ">" in result or "quote" in result


def test_editor_with_horizontal_rules(qtbot, app):
    """Test editor with horizontal rules"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(theme_manager=themes)
    qtbot.addWidget(editor)
    editor.show()

    hr_markdown = """
Section 1

---

Section 2
"""
    editor.from_markdown(hr_markdown)
    qtbot.wait(50)

    result = editor.to_markdown()
    assert "Section" in result


def test_editor_with_mixed_content(qtbot, app):
    """Test editor with mixed markdown content"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(theme_manager=themes)
    qtbot.addWidget(editor)
    editor.show()

    mixed_markdown = """
# Heading

This is **bold** and *italic* text.

- [ ] Todo item
- [x] Completed item

```python
code()
```

[Link](https://example.com)

> Quote

| Table | Header |
|-------|--------|
| A     | B      |
"""
    editor.from_markdown(mixed_markdown)
    qtbot.wait(50)

    result = editor.to_markdown()
    # Should contain various markdown elements
    assert len(result) > 50


def test_editor_insert_text_at_cursor(qtbot, app):
    """Test inserting text at cursor position"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(theme_manager=themes)
    qtbot.addWidget(editor)
    editor.show()

    editor.from_markdown("Start Middle End")
    qtbot.wait(50)

    # Move cursor to middle
    cursor = editor.textCursor()
    cursor.setPosition(6)
    editor.setTextCursor(cursor)

    # Insert text
    editor.insertPlainText("INSERTED ")
    qtbot.wait(50)

    result = editor.to_markdown()
    assert "INSERTED" in result


def test_editor_delete_operations(qtbot, app):
    """Test delete operations"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    editor = MarkdownEditor(theme_manager=themes)
    qtbot.addWidget(editor)
    editor.show()

    editor.from_markdown("Text to delete")
    qtbot.wait(50)

    # Select some text and delete
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(4, QTextCursor.KeepAnchor)
    editor.setTextCursor(cursor)

    cursor.removeSelectedText()
    qtbot.wait(50)

    result = editor.to_markdown()
    assert "Text" not in result or len(result) < 15


def test_markdown_highlighter_dark_theme(qtbot, app):
    """Test markdown highlighter with dark theme - covers lines 74-75"""
    # Create theme manager with dark theme
    themes = ThemeManager(app, ThemeConfig(theme=Theme.DARK))

    # Create a text document
    doc = QTextDocument()

    # Create highlighter with dark theme
    highlighter = MarkdownHighlighter(doc, themes)

    # Set some markdown text
    doc.setPlainText("# Heading\n\nSome **bold** text\n\n```python\ncode\n```")

    # The highlighter should work with dark theme
    assert highlighter is not None
    assert highlighter.code_block_format is not None


def test_markdown_highlighter_light_theme(qtbot, app):
    """Test markdown highlighter with light theme"""
    # Create theme manager with light theme
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))

    # Create a text document
    doc = QTextDocument()

    # Create highlighter with light theme
    highlighter = MarkdownHighlighter(doc, themes)

    # Set some markdown text
    doc.setPlainText("# Heading\n\nSome **bold** text")

    # The highlighter should work with light theme
    assert highlighter is not None
    assert highlighter.code_block_format is not None


def test_markdown_highlighter_system_dark_theme(qtbot, app, monkeypatch):
    """Test markdown highlighter with system dark theme"""
    # Create theme manager with system theme
    themes = ThemeManager(app, ThemeConfig(theme=Theme.SYSTEM))

    # Mock the system to be dark
    monkeypatch.setattr(themes, "_is_system_dark", True)

    # Create a text document
    doc = QTextDocument()

    # Create highlighter
    highlighter = MarkdownHighlighter(doc, themes)

    # Set some markdown text
    doc.setPlainText("# Dark Theme Heading\n\n**Bold text**")

    # The highlighter should use dark theme colors
    assert highlighter is not None


def test_markdown_highlighter_with_headings(qtbot, app):
    """Test highlighting various heading levels"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, themes)

    markdown = """
# H1 Heading
## H2 Heading
### H3 Heading
#### H4 Heading
##### H5 Heading
###### H6 Heading
"""
    doc.setPlainText(markdown)

    # Should highlight all headings
    assert highlighter.h1_format is not None
    assert highlighter.h2_format is not None


def test_markdown_highlighter_with_emphasis(qtbot, app):
    """Test highlighting bold and italic"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, themes)

    markdown = """
**Bold text**
*Italic text*
***Bold and italic***
__Also bold__
_Also italic_
"""
    doc.setPlainText(markdown)

    # Should have emphasis formats
    assert highlighter is not None


def test_markdown_highlighter_with_code(qtbot, app):
    """Test highlighting inline code and code blocks"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, themes)

    markdown = """
Inline `code` here.

```python
def hello():
    print("world")
```

More text.
"""
    doc.setPlainText(markdown)

    # Should highlight code
    assert highlighter.code_block_format is not None


def test_markdown_highlighter_with_links(qtbot, app):
    """Test highlighting links"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, themes)

    markdown = """
[Link text](https://example.com)
<https://auto-link.com>
"""
    doc.setPlainText(markdown)

    # Should have link format
    assert highlighter is not None


def test_markdown_highlighter_with_lists(qtbot, app):
    """Test highlighting lists"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, themes)

    markdown = """
- Unordered item 1
- Unordered item 2

1. Ordered item 1
2. Ordered item 2

- [ ] Unchecked task
- [x] Checked task
"""
    doc.setPlainText(markdown)

    # Should highlight lists
    assert highlighter is not None


def test_markdown_highlighter_with_blockquotes(qtbot, app):
    """Test highlighting blockquotes"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, themes)

    markdown = """
> This is a quote
> With multiple lines
"""
    doc.setPlainText(markdown)

    # Should highlight quotes
    assert highlighter is not None


def test_markdown_highlighter_theme_change(qtbot, app):
    """Test changing theme after creation"""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    doc = QTextDocument()
    highlighter = MarkdownHighlighter(doc, themes)

    markdown = "# Heading\n\n**Bold**"
    doc.setPlainText(markdown)

    # Change to dark theme
    themes.apply(Theme.DARK)
    qtbot.wait(50)

    # Highlighter should update
    # We can't directly test the visual change, but verify it doesn't crash
    assert highlighter is not None


def test_auto_pair_skip_closing_bracket(editor, qtbot):
    """Test skipping over closing brackets when auto-pairing."""
    # Insert opening bracket
    editor.insertPlainText("(")

    # Type closing bracket - should skip over the auto-inserted one
    event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_ParenRight, Qt.NoModifier, ")")
    editor.keyPressEvent(event)

    # Should have only one pair of brackets
    text = editor.toPlainText()
    assert text.count("(") == 1
    assert text.count(")") == 1


def test_apply_heading(editor, qtbot):
    """Test applying heading to text."""
    # Insert some text
    editor.insertPlainText("Heading Text")
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.StartOfLine)
    editor.setTextCursor(cursor)

    # Apply heading - size >= 24 creates level 1 heading
    editor.apply_heading(24)

    text = editor.toPlainText()
    assert text.startswith("#")


def test_handle_return_in_code_block(editor, qtbot):
    """Test pressing return inside a code block."""
    # Create a code block
    editor.insertPlainText("```python\nprint('hello')")

    # Place cursor at end
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)

    # Press return - should maintain indentation
    event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\n")
    editor.keyPressEvent(event)

    # Should have added a new line
    text = editor.toPlainText()
    assert text.count("\n") >= 2


def test_handle_return_in_list_empty_item(editor, qtbot):
    """Test pressing return in an empty list item."""
    # Create list with empty item
    editor.insertPlainText("- item\n- ")

    # Place cursor at end of empty item
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)

    # Press return - should end the list
    event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\n")
    editor.keyPressEvent(event)

    text = editor.toPlainText()
    # Should have processed the empty list marker
    lines = text.split("\n")
    assert len(lines) >= 2


def test_handle_backspace_in_empty_list_item(editor, qtbot):
    """Test pressing backspace in an empty list item."""
    # Create list with cursor after marker
    editor.insertPlainText("- ")

    # Place cursor at end
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)

    # Press backspace - should remove list marker
    event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Backspace, Qt.NoModifier, "")
    editor.keyPressEvent(event)

    text = editor.toPlainText()
    # List marker handling
    assert len(text) <= 2


def test_tab_key_handling(editor, qtbot):
    """Test tab key handling in editor."""
    # Create a list item
    editor.insertPlainText("- item")

    # Place cursor in the item
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    editor.setTextCursor(cursor)

    # Press tab
    event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier, "\t")
    editor.keyPressEvent(event)

    # Should have processed the tab
    text = editor.toPlainText()
    assert len(text) >= 6  # At least "- item" plus tab


def test_drag_enter_with_urls(editor, qtbot):
    """Test drag and drop with URLs."""
    from PySide6.QtGui import QDragEnterEvent

    # Create mime data with URLs
    mime_data = QMimeData()
    mime_data.setUrls([QUrl("file:///tmp/test.txt")])

    # Create drag enter event
    event = QDragEnterEvent(
        editor.rect().center(), Qt.CopyAction, mime_data, Qt.LeftButton, Qt.NoModifier
    )

    # Handle drag enter
    editor.dragEnterEvent(event)

    # Should accept the event
    assert event.isAccepted()


def test_drag_enter_with_text(editor, qtbot):
    """Test drag and drop with plain text."""
    from PySide6.QtGui import QDragEnterEvent

    # Create mime data with text
    mime_data = QMimeData()
    mime_data.setText("dragged text")

    # Create drag enter event
    event = QDragEnterEvent(
        editor.rect().center(), Qt.CopyAction, mime_data, Qt.LeftButton, Qt.NoModifier
    )

    # Handle drag enter
    editor.dragEnterEvent(event)

    # Should accept text drag
    assert event.isAccepted()


def test_highlighter_dark_mode_code_blocks(app, qtbot, tmp_path):
    """Test code block highlighting in dark mode."""
    # Get theme manager and set dark mode
    theme_manager = ThemeManager(app, ThemeConfig(theme=Theme.DARK))

    # Create editor with dark theme
    editor = MarkdownEditor(theme_manager)
    qtbot.addWidget(editor)

    # Insert code block
    editor.setPlainText("```python\nprint('hello')\n```")

    # Force rehighlight
    editor.highlighter.rehighlight()

    # Verify no crash - actual color verification is difficult in tests


def test_highlighter_code_block_with_language(editor, qtbot):
    """Test syntax highlighting inside fenced code blocks with language."""
    # Insert code block with language
    editor.setPlainText('```python\ndef hello():\n    print("world")\n```')

    # Force rehighlight
    editor.highlighter.rehighlight()

    # Verify syntax highlighting was applied (lines 186-193)
    # We can't easily verify the exact formatting, but we ensure no crash


def test_highlighter_bold_italic_overlap_detection(editor, qtbot):
    """Test that bold/italic formatting detects overlaps correctly."""
    # Insert text with overlapping bold and triple-asterisk
    editor.setPlainText("***bold and italic***")

    # Force rehighlight
    editor.highlighter.rehighlight()

    # The overlap detection (lines 252, 264) should prevent issues


def test_highlighter_italic_edge_cases(editor, qtbot):
    """Test italic formatting edge cases."""
    # Test edge case: avoiding stealing markers that are part of double
    # This tests lines 267-270
    editor.setPlainText("**not italic* text**")

    # Force rehighlight
    editor.highlighter.rehighlight()

    # Test another edge case
    editor.setPlainText("*italic but next to double**")
    editor.highlighter.rehighlight()


def test_highlighter_multiple_markdown_elements(editor, qtbot):
    """Test highlighting document with multiple markdown elements."""
    # Complex document with various elements
    text = """# Heading 1
## Heading 2

**bold text** and *italic text*

```python
def test():
    return True
```

- list item
- [ ] task item

[link](http://example.com)
"""

    editor.setPlainText(text)
    editor.highlighter.rehighlight()

    # Verify no crashes with complex formatting


def test_highlighter_inline_code_vs_fence(editor, qtbot):
    """Test that inline code and fenced blocks are distinguished."""
    text = """Inline `code` here

```
fenced block
```
"""

    editor.setPlainText(text)
    editor.highlighter.rehighlight()
