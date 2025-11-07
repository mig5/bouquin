from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QTextCursor
from PySide6.QtTest import QTest

from tests.qt_helpers import trigger_menu_action


def _cursor_info(editor):
    """Return (start, end, selectedText) for the current selection."""
    tc: QTextCursor = editor.textCursor()
    start = min(tc.anchor(), tc.position())
    end = max(tc.anchor(), tc.position())
    return start, end, tc.selectedText()


def test_find_actions_and_shortcuts(open_window, qtbot):
    win = open_window

    # Actions should be present under Navigate and advertise canonical shortcuts
    act_find = trigger_menu_action(win, "Find on page")
    assert act_find.shortcut().matches(QKeySequence.Find) == QKeySequence.ExactMatch

    act_next = trigger_menu_action(win, "Find Next")
    assert act_next.shortcut().matches(QKeySequence.FindNext) == QKeySequence.ExactMatch

    act_prev = trigger_menu_action(win, "Find Previous")
    assert (
        act_prev.shortcut().matches(QKeySequence.FindPrevious)
        == QKeySequence.ExactMatch
    )

    # "Find on page" should open the bar and focus the input
    act_find.trigger()
    qtbot.waitUntil(lambda: win.findBar.isVisible())
    qtbot.waitUntil(lambda: win.findBar.edit.hasFocus())


def test_find_navigate_case_sensitive_and_close_focus(open_window, qtbot):
    win = open_window

    # Mixed-case content with three matches
    text = "alpha … ALPHA … alpha"
    win.editor.setPlainText(text)
    qtbot.waitUntil(lambda: win.editor.toPlainText() == text)

    # Open the find bar from the menu
    trigger_menu_action(win, "Find on page").trigger()
    qtbot.waitUntil(lambda: win.findBar.isVisible())
    win.findBar.edit.clear()
    QTest.keyClicks(win.findBar.edit, "alpha")

    # 1) First hit (case-insensitive default)
    QTest.keyClick(win.findBar.edit, Qt.Key_Return)
    qtbot.waitUntil(lambda: win.editor.textCursor().hasSelection())
    s0, e0, sel0 = _cursor_info(win.editor)
    assert sel0.lower() == "alpha"

    # 2) Next → uppercase ALPHA (case-insensitive)
    trigger_menu_action(win, "Find Next").trigger()
    qtbot.waitUntil(lambda: win.editor.textCursor().hasSelection())
    s1, e1, sel1 = _cursor_info(win.editor)
    assert sel1.upper() == "ALPHA"

    # 3) Next → the *other* lowercase "alpha"
    trigger_menu_action(win, "Find Next").trigger()
    qtbot.waitUntil(lambda: win.editor.textCursor().hasSelection())
    s2, e2, sel2 = _cursor_info(win.editor)
    assert sel2.lower() == "alpha"
    # Ensure we didn't wrap back to the very first "alpha"
    assert s2 != s0

    # 4) Case-sensitive: skip ALPHA and only hit lowercase
    win.findBar.case.setChecked(True)
    # Put the caret at start to make the next search deterministic
    tc = win.editor.textCursor()
    tc.setPosition(0)
    win.editor.setTextCursor(tc)

    win.findBar.find_next()
    qtbot.waitUntil(lambda: win.editor.textCursor().hasSelection())
    s_cs1, e_cs1, sel_cs1 = _cursor_info(win.editor)
    assert sel_cs1 == "alpha"

    win.findBar.find_next()
    qtbot.waitUntil(lambda: win.editor.textCursor().hasSelection())
    s_cs2, e_cs2, sel_cs2 = _cursor_info(win.editor)
    assert sel_cs2 == "alpha"
    assert s_cs2 != s_cs1  # it's the other lowercase match

    # 5) Previous goes back to the earlier lowercase match
    win.findBar.find_prev()
    qtbot.waitUntil(lambda: win.editor.textCursor().hasSelection())
    s_prev, e_prev, sel_prev = _cursor_info(win.editor)
    assert sel_prev == "alpha"
    assert s_prev == s_cs1

    # 6) Close returns focus to editor
    win.findBar.closeBtn.click()
    qtbot.waitUntil(lambda: not win.findBar.isVisible())
    qtbot.waitUntil(lambda: win.editor.hasFocus())
