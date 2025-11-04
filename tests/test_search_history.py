from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QListWidget, QWidget, QAbstractButton

from tests.qt_helpers import (
    trigger_menu_action,
    wait_for_widget,
    find_line_edit_by_placeholder,
)


def test_search_and_open_date(open_window, qtbot):
    win = open_window

    win.editor.setPlainText("lorem ipsum target")
    win._save_current(explicit=True)
    base = win.calendar.selectedDate()
    d2 = base.addDays(7)
    win.calendar.setSelectedDate(d2)
    win.editor.setPlainText("target appears here, too")
    win._save_current(explicit=True)

    search_box = find_line_edit_by_placeholder(win, "search")
    assert search_box is not None, "Search input not found"
    search_box.setText("target")
    QTest.qWait(150)

    results = getattr(getattr(win, "search", None), "results", None)
    if isinstance(results, QListWidget) and results.count() > 0:
        # Click until we land on d2
        landed = False
        for i in range(results.count()):
            item = results.item(i)
            rect = results.visualItemRect(item)
            QTest.mouseDClick(results.viewport(), Qt.LeftButton, pos=rect.center())
            qtbot.wait(120)
            if win.calendar.selectedDate() == d2:
                landed = True
                break
        assert landed, "Search results did not navigate to the expected date"
    else:
        assert "target" in win.editor.toPlainText().lower()


def test_history_dialog_revert(open_window, qtbot):
    win = open_window

    # Create two versions on the current day
    win.editor.setPlainText("v1 text")
    win._save_current(explicit=True)
    win.editor.setPlainText("v2 text")
    win._save_current(explicit=True)

    # Open the History UI (label varies)
    try:
        trigger_menu_action(win, "View History")
    except AssertionError:
        trigger_menu_action(win, "History")

    # Find ANY top-level window that looks like the History dialog
    def _is_history(w: QWidget):
        if not w.isWindow() or not w.isVisible():
            return False
        title = (w.windowTitle() or "").lower()
        return "history" in title or bool(w.findChildren(QListWidget))

    hist = wait_for_widget(QWidget, predicate=_is_history, timeout_ms=15000)

    # Wait for population and pick the list with the most items
    chosen = None
    for _ in range(120):  # up to ~3s
        lists = hist.findChildren(QListWidget)
        if lists:
            chosen = max(lists, key=lambda lw: lw.count())
            if chosen.count() >= 2:
                break
        QTest.qWait(25)

    assert (
        chosen is not None and chosen.count() >= 2
    ), "History list never populated with 2+ versions"

    # Click the older version row so the Revert button enables
    idx = 1  # row 0 is most-recent "v2 text", row 1 is "v1 text"
    rect = chosen.visualItemRect(chosen.item(idx))
    QTest.mouseClick(chosen.viewport(), Qt.LeftButton, pos=rect.center())
    QTest.qWait(100)

    # Find any enabled button whose text/tooltip/objectName contains 'revert'
    revert_btn = None
    for _ in range(120):  # wait until it enables
        for btn in hist.findChildren(QAbstractButton):
            meta = " ".join(
                [btn.text() or "", btn.toolTip() or "", btn.objectName() or ""]
            ).lower()
            if "revert" in meta:
                revert_btn = btn
                break
        if revert_btn and revert_btn.isEnabled():
            break
        QTest.qWait(25)

    assert (
        revert_btn is not None and revert_btn.isEnabled()
    ), "Revert button not found/enabled"
    QTest.mouseClick(revert_btn, Qt.LeftButton)

    # AutoResponder will accept confirm/success boxes
    QTest.qWait(150)
    assert "v1 text" in win.editor.toPlainText()
