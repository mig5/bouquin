from PySide6.QtCore import Qt, QMimeData, QPoint, QUrl
from PySide6.QtGui import QImage, QMouseEvent, QKeyEvent, QTextCursor, QTextImageFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from bouquin.editor import Editor
from bouquin.theme import ThemeManager, ThemeConfig, Theme

import re


def _mk_editor() -> Editor:
    # pytest-qt ensures a QApplication exists
    app = QApplication.instance()
    tm = ThemeManager(app, ThemeConfig())
    return Editor(tm)


def _move_cursor_to_first_image(editor: Editor) -> QTextImageFormat | None:
    c = editor.textCursor()
    c.movePosition(QTextCursor.Start)
    while True:
        c2 = QTextCursor(c)
        c2.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
        if c2.position() == c.position():
            break
        fmt = c2.charFormat()
        if fmt.isImageFormat():
            editor.setTextCursor(c2)
            return QTextImageFormat(fmt)
        c.movePosition(QTextCursor.Right)
    return None


def _fmt_at(editor: Editor, pos: int):
    c = editor.textCursor()
    c.setPosition(pos)
    c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 1)
    return c.charFormat()


def test_space_breaks_link_anchor_and_styling(qtbot):
    e = _mk_editor()
    e.resize(600, 300)
    e.show()
    qtbot.waitExposed(e)

    # Type a URL, which should be linkified (anchor + underline + blue)
    url = "https://mig5.net"
    QTest.keyClicks(e, url)
    qtbot.waitUntil(lambda: e.toPlainText() == url)

    # Sanity: characters within the URL are anchors
    for i in range(len(url)):
        assert _fmt_at(e, i).isAnchor()

    # Hit Space – Editor.keyPressEvent() should call _break_anchor_for_next_char()
    QTest.keyClick(e, Qt.Key_Space)

    # Type some normal text; it must not inherit the link formatting
    tail = "this is a test"
    QTest.keyClicks(e, tail)
    qtbot.waitUntil(lambda: e.toPlainText().endswith(tail))

    txt = e.toPlainText()
    # Find where our 'tail' starts
    start = txt.index(tail)
    end = start + len(tail)

    # None of the trailing characters should be part of an anchor or visually underlined
    for i in range(start, end):
        fmt = _fmt_at(e, i)
        assert not fmt.isAnchor(), f"char {i} unexpectedly still has an anchor"
        assert not fmt.fontUnderline(), f"char {i} unexpectedly still underlined"

    # Optional: ensure the HTML only wraps the URL in <a>, not the trailing text
    html = e.document().toHtml()
    assert re.search(
        r'<a [^>]*href="https?://mig5\.net"[^>]*>(?:<span[^>]*>)?https?://mig5\.net(?:</span>)?</a>\s+this is a test',
        html,
        re.S,
    ), html
    assert "this is a test</a>" not in html


def test_embed_qimage_saved_as_data_url(qtbot):
    e = _mk_editor()
    e.resize(600, 400)
    qtbot.addWidget(e)
    e.show()
    qtbot.waitExposed(e)

    img = QImage(60, 40, QImage.Format_ARGB32)
    img.fill(0xFF336699)
    e._insert_qimage_at_cursor(img, autoscale=False)

    html = e.to_html_with_embedded_images()
    assert "data:image/png;base64," in html


def test_insert_images_autoscale_and_fit(qtbot, tmp_path):
    # Create a very wide image so autoscale triggers
    big = QImage(2000, 800, QImage.Format_ARGB32)
    big.fill(0xFF00FF00)
    big_path = tmp_path / "big.png"
    big.save(str(big_path))

    e = _mk_editor()
    e.resize(420, 300)  # known viewport width
    qtbot.addWidget(e)
    e.show()
    qtbot.waitExposed(e)

    e.insert_images([str(big_path)], autoscale=True)

    # Cursor lands after the image + a blank block; helper will select the image char
    fmt = _move_cursor_to_first_image(e)
    assert fmt is not None

    # After autoscale, width should be <= ~92% of viewport
    max_w = int(e.viewport().width() * 0.92)
    assert fmt.width() <= max_w + 1  # allow off-by-1 from rounding

    # Now exercise "fit to editor width"
    e._fit_image_to_editor_width()
    _tc, fmt2, _orig = e._image_info_at_cursor()
    assert fmt2 is not None
    assert abs(fmt2.width() - max_w) <= 1


def test_linkify_trims_trailing_punctuation(qtbot):
    e = _mk_editor()
    qtbot.addWidget(e)
    e.show()
    qtbot.waitExposed(e)

    e.setPlainText("See (https://example.com).")
    # Wait until linkification runs (connected to textChanged)
    qtbot.waitUntil(lambda: 'href="' in e.document().toHtml())

    html = e.document().toHtml()
    # Anchor should *not* include the closing ')'
    assert 'href="https://example.com"' in html
    assert 'href="https://example.com)."' not in html


def test_code_block_enter_exits_on_empty_line(qtbot):

    e = _mk_editor()
    qtbot.addWidget(e)
    e.show()
    qtbot.waitExposed(e)

    e.setPlainText("code")
    c = e.textCursor()
    c.select(QTextCursor.BlockUnderCursor)
    e.setTextCursor(c)
    e.apply_code()

    # Put caret at end of the code block, then Enter to create an empty line *inside* the frame
    c = e.textCursor()
    c.movePosition(QTextCursor.EndOfBlock)
    e.setTextCursor(c)

    QTest.keyClick(e, Qt.Key_Return)
    # Ensure we are on an empty block *inside* the code frame
    qtbot.waitUntil(
        lambda: e._nearest_code_frame(e.textCursor(), tolerant=False) is not None
        and e.textCursor().block().length() == 1
    )

    # Second Enter should jump *out* of the frame
    QTest.keyClick(e, Qt.Key_Return)


class DummyMenu:
    def __init__(self):
        self.seps = 0
        self.subs = []
        self.exec_called = False

    def addSeparator(self):
        self.seps += 1

    def addMenu(self, title):
        m = DummyMenu()
        self.subs.append((title, m))
        return m

    def addAction(self, *a, **k):
        pass

    def exec(self, *a, **k):
        self.exec_called = True


def _themes():
    app = QApplication.instance()
    return ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))


def test_context_menu_adds_image_actions(monkeypatch, qtbot):
    e = Editor(_themes())
    qtbot.addWidget(e)
    # Fake an image at cursor
    qi = QImage(10, 10, QImage.Format_ARGB32)
    qi.fill(0xFF00FF00)
    imgfmt = QTextImageFormat()
    imgfmt.setName("x")
    imgfmt.setWidth(10)
    imgfmt.setHeight(10)
    tc = e.textCursor()
    monkeypatch.setattr(e, "_image_info_at_cursor", lambda: (tc, imgfmt, qi))

    dummy = DummyMenu()
    monkeypatch.setattr(e, "createStandardContextMenu", lambda: dummy)

    class Evt:
        def globalPos(self):
            return QPoint(0, 0)

    e.contextMenuEvent(Evt())
    assert dummy.exec_called
    assert dummy.seps == 1
    assert any(t == "Image size" for t, _ in dummy.subs)


def test_insert_from_mime_image_and_urls(tmp_path, qtbot):
    e = Editor(_themes())
    qtbot.addWidget(e)
    # Build a mime with an image
    mime = QMimeData()
    img = QImage(6, 6, QImage.Format_ARGB32)
    img.fill(0xFF0000FF)
    mime.setImageData(img)
    e.insertFromMimeData(mime)
    html = e.document().toHtml()
    assert "<img" in html

    # Now with urls: local non-image + local image + remote url
    png = tmp_path / "t.png"
    img.save(str(png))
    txt = tmp_path / "x.txt"
    txt.write_text("hi", encoding="utf-8")
    mime2 = QMimeData()
    mime2.setUrls(
        [
            QUrl.fromLocalFile(str(txt)),
            QUrl.fromLocalFile(str(png)),
            QUrl("https://example.com/file"),
        ]
    )
    e.insertFromMimeData(mime2)
    h2 = e.document().toHtml()
    assert 'href="file://' in h2  # local file link inserted
    assert "<img" in h2  # image inserted
    assert 'href="https://example.com/file"' in h2  # remote url link


def test_mouse_release_ctrl_click_opens(monkeypatch, qtbot):
    e = Editor(_themes())
    qtbot.addWidget(e)
    # Anchor under cursor
    monkeypatch.setattr(e, "anchorAt", lambda p: "https://example.com")
    opened = {}
    from PySide6.QtGui import QDesktopServices as DS

    monkeypatch.setattr(
        DS, "openUrl", lambda url: opened.setdefault("u", url.toString())
    )
    ev = QMouseEvent(
        QMouseEvent.MouseButtonRelease,
        QPoint(1, 1),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.ControlModifier,
    )
    e.mouseReleaseEvent(ev)
    assert opened.get("u") == "https://example.com"


def test_keypress_space_breaks_anchor(monkeypatch, qtbot):
    e = Editor(_themes())
    qtbot.addWidget(e)
    called = {}
    monkeypatch.setattr(
        e, "_break_anchor_for_next_char", lambda: called.setdefault("x", True)
    )
    ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " ")
    e.keyPressEvent(ev)
    assert called.get("x") is True


def test_enter_leaves_code_frame(qtbot):
    e = Editor(_themes())
    qtbot.addWidget(e)
    e.setPlainText("")
    # Insert a code block frame
    e.apply_code()
    # Place cursor inside the empty code block
    c = e.textCursor()
    c.movePosition(QTextCursor.End)
    e.setTextCursor(c)
    # Press Enter; should jump outside the frame and start normal paragraph
    ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
    e.keyPressEvent(ev)
    # After enter, the cursor should not be inside a code frame
    assert e._nearest_code_frame(e.textCursor(), tolerant=False) is None


def test_space_does_not_bleed_anchor_format(qtbot):
    e = _mk_editor()
    qtbot.addWidget(e)
    e.show()
    qtbot.waitExposed(e)

    e.setPlainText("https://a.example")
    qtbot.waitUntil(lambda: 'href="' in e.document().toHtml())

    c = e.textCursor()
    c.movePosition(QTextCursor.End)
    e.setTextCursor(c)

    # Press Space; keyPressEvent should break the anchor for the next char
    QTest.keyClick(e, Qt.Key_Space)
    assert e.currentCharFormat().isAnchor() is False


def test_editor_small_helpers(qtbot):
    app = QApplication.instance()
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    e = Editor(themes)
    qtbot.addWidget(e)
    # _approx returns True when |a-b| <= eps
    assert e._approx(1.0, 1.25, eps=0.3) is True
    assert e._approx(1.0, 1.6, eps=0.3) is False
    # Exercise helpers
    _ = e._is_heading_typing()
    e._apply_normal_typing()
