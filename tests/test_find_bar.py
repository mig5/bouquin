import pytest

from PySide6.QtGui import QTextCursor
from bouquin.markdown_editor import MarkdownEditor
from bouquin.theme import ThemeManager, ThemeConfig, Theme


@pytest.fixture
def editor(app, qtbot):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    ed = MarkdownEditor(themes)
    qtbot.addWidget(ed)
    ed.show()
    return ed


from bouquin.find_bar import FindBar


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
    from PySide6.QtGui import QTextCursor

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
