import pytest

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import (
    QImage,
    QColor,
    QKeyEvent,
    QTextCursor,
    QTextDocument,
    QFont,
    QTextCharFormat,
)
from PySide6.QtWidgets import QTextEdit

from bouquin.markdown_editor import MarkdownEditor
from bouquin.markdown_highlighter import MarkdownHighlighter
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


@pytest.mark.gui
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
    editor.apply_code()  # </> action inserts fenced code block
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
    # Light theme path (covers lines ~74-75 in _on_theme_changed)
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
    Triggers the end-following guard for italic (line ~208), e.g. '*i**'.
    """
    doc, hl = hl_light
    doc.setPlainText("*i**")
    hl.rehighlight()
    # The 'i' should not get italic due to the guard (closing '*' followed by '*')
    f = fmt(doc, 0, 1)
    assert not f.fontItalic()


@pytest.mark.gui
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


@pytest.mark.gui
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


@pytest.mark.gui
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
