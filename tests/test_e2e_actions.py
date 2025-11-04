from PySide6.QtCore import QUrl, QObject, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from tests.qt_helpers import trigger_menu_action


def test_launch_write_save_and_navigate(open_window, qtbot, today_iso):
    win = open_window
    win.editor.setPlainText("Hello Bouquin")
    qtbot.waitUntil(lambda: win.editor.toPlainText() == "Hello Bouquin", timeout=15000)

    trigger_menu_action(win, "Save a version")  # AutoResponder clicks OK

    versions = win.db.list_versions(today_iso)
    assert versions and versions[0]["is_current"] == 1

    selected = win.calendar.selectedDate()
    trigger_menu_action(win, "Next Day")
    qtbot.waitUntil(lambda: win.calendar.selectedDate() == selected.addDays(1))
    trigger_menu_action(win, "Previous Day")
    qtbot.waitUntil(lambda: win.calendar.selectedDate() == selected)
    win.calendar.setSelectedDate(selected.addDays(3))
    trigger_menu_action(win, "Today")
    qtbot.waitUntil(lambda: win.calendar.selectedDate() == selected)


def test_help_menu_opens_urls(open_window, qtbot):
    opened: list[str] = []

    class UrlCatcher(QObject):
        @Slot(QUrl)
        def handle(self, url: QUrl):
            opened.append(url.toString())

    catcher = UrlCatcher()
    # Qt6/PySide6: setUrlHandler(scheme, receiver, methodName)
    QDesktopServices.setUrlHandler("https", catcher, "handle")
    QDesktopServices.setUrlHandler("http", catcher, "handle")
    try:
        win = open_window
        trigger_menu_action(win, "Documentation")
        trigger_menu_action(win, "Report a bug")
        QTest.qWait(150)
        assert len(opened) >= 2
    finally:
        QDesktopServices.unsetUrlHandler("https")
        QDesktopServices.unsetUrlHandler("http")


def test_idle_lock_and_unlock(open_window, qtbot):
    win = open_window
    win._enter_lock()
    assert getattr(win, "_locked", False) is True
    win._on_unlock_clicked()  # AutoResponder types 'ci-secret-key'
    qtbot.waitUntil(lambda: getattr(win, "_locked", True) is False, timeout=15000)
