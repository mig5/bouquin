import pytest

from PySide6.QtGui import QTextCursor
from bouquin.markdown_editor import MarkdownEditor
from bouquin.theme import ThemeManager, ThemeConfig, Theme
from bouquin.find_bar import FindBar


@pytest.fixture
def editor(app, qtbot):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    ed = MarkdownEditor(themes)
    qtbot.addWidget(ed)
    ed.show()
    return ed


@pytest.mark.gui
def test_findbar_basic_navigation(qtbot, editor):
    editor.from_markdown("alpha\nbeta\nalpha\nGamma\n")
    editor.moveCursor(QTextCursor.Start)

    fb = FindBar(editor, parent=editor)
    qtbot.addWidget(fb)
    fb.show_bar()
    fb.edit.setText("alpha")
    fb.find_next()
    pos1 = editor.textCursor().position()
    fb.find_next()
    pos2 = editor.textCursor().position()
    assert pos2 > pos1

    fb.find_prev()
    pos3 = editor.textCursor().position()
    assert pos3 <= pos2

    fb.case.setChecked(True)
    fb.refresh()
    fb.hide_bar()


def test_show_bar_seeds_selection(qtbot, editor):

    editor.from_markdown("alpha beta")
    c = editor.textCursor()
    c.movePosition(QTextCursor.Start)
    c.movePosition(QTextCursor.NextWord, QTextCursor.KeepAnchor)
    editor.setTextCursor(c)

    fb = FindBar(editor, parent=editor)
    qtbot.addWidget(fb)
    fb.show_bar()
    assert fb.edit.text().lower() == "alpha"
    fb.hide_bar()


def test_show_bar_no_editor(qtbot, app):
    fb = FindBar(lambda: None)
    qtbot.addWidget(fb)
    fb.show_bar()  # should early return without crashing and not become visible
    assert not fb.isVisible()


def test_show_bar_ignores_multi_paragraph_selection(qtbot, editor):
    editor.from_markdown("alpha\n\nbeta")
    c = editor.textCursor()
    c.movePosition(QTextCursor.Start)
    # Select across the paragraph separator U+2029 equivalent – select more than one block
    c.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
    editor.setTextCursor(c)
    fb = FindBar(lambda: editor, parent=editor)
    qtbot.addWidget(fb)
    fb.show_bar()
    assert fb.edit.text() == ""  # should not seed with multi-paragraph
    fb.hide_bar()


def test_find_wraps_and_bumps_caret(qtbot, editor):
    editor.from_markdown("alpha alpha alpha")
    fb = FindBar(lambda: editor, parent=editor)
    qtbot.addWidget(fb)
    fb.edit.setText("alpha")

    # Select the first occurrence so caret bumping path triggers
    c = editor.textCursor()
    c.movePosition(QTextCursor.Start)
    c.movePosition(QTextCursor.NextWord, QTextCursor.KeepAnchor)
    editor.setTextCursor(c)

    fb.find_next()  # should bump to after current selection then find next
    sel = editor.textCursor().selectedText()
    assert sel.lower() == "alpha"

    # Force wrap to start by moving cursor to end then searching next
    c = editor.textCursor()
    c.movePosition(QTextCursor.End)
    editor.setTextCursor(c)
    fb.find_next()  # triggers wrap-to-start path
    assert editor.textCursor().hasSelection()


def test_update_highlight_clear_when_empty(qtbot, editor):
    editor.from_markdown("find me find me")
    fb = FindBar(lambda: editor, parent=editor)
    qtbot.addWidget(fb)
    fb.edit.setText("find")
    fb._update_highlight()
    assert editor.extraSelections()  # some highlights present

    fb.edit.setText("")
    fb._update_highlight()  # should clear
    assert not editor.extraSelections()


@pytest.mark.gui
def test_maybe_hide_and_wrap_prev(qtbot, editor):
    editor.setPlainText("a a a")
    fb = FindBar(editor=editor, shortcut_parent=editor)
    qtbot.addWidget(editor)
    qtbot.addWidget(fb)
    editor.show()
    fb.show()

    fb.edit.setText("a")
    fb._update_highlight()

    assert fb.isVisible()
    fb._maybe_hide()
    assert not fb.isVisible()

    fb.show_bar()
    c = editor.textCursor()
    c.movePosition(QTextCursor.Start)
    editor.setTextCursor(c)
    fb.find_prev()
