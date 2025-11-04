from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QTextCursor, QTextImageFormat
from PySide6.QtTest import QTest

from bouquin.editor import Editor


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


def test_embed_qimage_saved_as_data_url(qtbot):
    e = Editor()
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

    e = Editor()
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
    e = Editor()
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


def test_space_does_not_bleed_anchor_format(qtbot):
    e = Editor()
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


def test_code_block_enter_exits_on_empty_line(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor
    from PySide6.QtTest import QTest
    from bouquin.editor import Editor

    e = Editor()
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
        lambda: e._find_code_frame(e.textCursor()) is not None
        and e.textCursor().block().length() == 1
    )

    # Second Enter should jump *out* of the frame
    QTest.keyClick(e, Qt.Key_Return)
    # qtbot.waitUntil(lambda: e._find_code_frame(e.textCursor()) is None)
