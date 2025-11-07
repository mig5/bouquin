from PySide6.QtCore import Qt, QEvent, QUrl, QObject, Slot
from PySide6.QtGui import QImage, QMouseEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from bouquin.editor import Editor
from bouquin.theme import ThemeManager, ThemeConfig


def _mk_editor() -> Editor:
    app = QApplication.instance()
    tm = ThemeManager(app, ThemeConfig())
    e = Editor(tm)
    e.resize(700, 400)
    e.show()
    return e


def _point_for_char(e: Editor, pos: int):
    c = e.textCursor()
    c.setPosition(pos)
    r = e.cursorRect(c)
    return r.center()


def test_trim_url_and_linkify_and_ctrl_mouse(qtbot):
    e = _mk_editor()
    qtbot.addWidget(e)
    assert e._trim_url_end("https://ex.com)") == "https://ex.com"
    assert e._trim_url_end("www.mysite.org]") == "www.mysite.org"

    url = "https://example.org/path"
    QTest.keyClicks(e, url)
    qtbot.waitUntil(lambda: url in e.toPlainText())

    p = _point_for_char(e, 0)
    move = QMouseEvent(
        QEvent.MouseMove, p, Qt.NoButton, Qt.NoButton, Qt.ControlModifier
    )
    e.mouseMoveEvent(move)
    assert e.viewport().cursor().shape() == Qt.PointingHandCursor

    opened = {}

    class Catcher(QObject):
        @Slot(QUrl)
        def handle(self, u: QUrl):
            opened["u"] = u.toString()

    from PySide6.QtGui import QDesktopServices

    catcher = Catcher()
    QDesktopServices.setUrlHandler("https", catcher, "handle")
    try:
        rel = QMouseEvent(
            QEvent.MouseButtonRelease,
            p,
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.ControlModifier,
        )
        e.mouseReleaseEvent(rel)
        got_signal = []
        e.linkActivated.connect(lambda href: got_signal.append(href))
        e.mouseReleaseEvent(rel)
        assert opened or got_signal
    finally:
        QDesktopServices.unsetUrlHandler("https")


def test_insert_images_and_image_helpers(qtbot, tmp_path):
    e = _mk_editor()
    qtbot.addWidget(e)

    # No image under cursor yet (412 guard)
    tc, fmt, orig = e._image_info_at_cursor()
    assert tc is None and fmt is None and orig is None

    # Insert a real image file (574–584 path)
    img_path = tmp_path / "tiny.png"
    img = QImage(4, 4, QImage.Format_ARGB32)
    img.fill(0xFF336699)
    assert img.save(str(img_path), "PNG")
    e.insert_images([str(img_path)], autoscale=False)
    assert "<img" in e.toHtml()

    # Guards when not on an image (453, 464)
    e._scale_image_at_cursor(1.1)
    e._fit_image_to_editor_width()


def test_checkbox_click_and_enter_continuation(qtbot):
    e = _mk_editor()
    qtbot.addWidget(e)
    e.setPlainText("☐ task one")

    # Need it visible for mouse coords
    e.resize(600, 300)
    e.show()
    qtbot.waitExposed(e)

    # Click on the checkbox glyph to toggle (605–614)
    start_point = _point_for_char(e, 0)
    press = QMouseEvent(
        QEvent.MouseButtonPress,
        start_point,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    e.mousePressEvent(press)
    assert e.toPlainText().startswith("☑ ")

    # Press Enter at end -> new line with fresh checkbox (680–684)
    c = e.textCursor()
    c.movePosition(QTextCursor.End)
    e.setTextCursor(c)
    QTest.keyClick(e, Qt.Key_Return)
    lines = e.toPlainText().splitlines()
    assert len(lines) >= 2 and lines[1].startswith("☐ ")


def test_heading_and_lists_toggle_remove(qtbot):
    e = _mk_editor()
    qtbot.addWidget(e)
    e.setPlainText("para")

    # "Normal" path is size=0 (904…)
    e.apply_heading(0)

    # bullets twice -> second call removes (945–946)
    e.toggle_bullets()
    e.toggle_bullets()
    # numbers twice -> second call removes (955–956)
    e.toggle_numbers()
    e.toggle_numbers()
