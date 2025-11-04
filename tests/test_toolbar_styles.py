from PySide6.QtGui import QTextCursor, QFont
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


def test_toggle_basic_char_styles(open_window, qtbot):
    win = open_window
    win.editor.setPlainText("style")
    c = win.editor.textCursor()
    c.select(QTextCursor.Document)
    win.editor.setTextCursor(c)
    win.toolBar.actBold.trigger()
    assert win.editor.currentCharFormat().fontWeight() == QFont.Weight.Bold
    win.toolBar.actItalic.trigger()
    assert win.editor.currentCharFormat().fontItalic() is True
    win.toolBar.actUnderline.trigger()
    assert win.editor.currentCharFormat().fontUnderline() is True
    win.toolBar.actStrike.trigger()
    assert win.editor.currentCharFormat().fontStrikeOut() is True


def test_headings_lists_and_alignment(open_window, qtbot):
    win = open_window
    win.editor.setPlainText("Heading\nSecond line")
    c = win.editor.textCursor()
    c.select(QTextCursor.LineUnderCursor)
    win.editor.setTextCursor(c)

    sizes = []
    for attr in ("actH1", "actH2", "actH3"):
        if hasattr(win.toolBar, attr):
            getattr(win.toolBar, attr).trigger()
            QTest.qWait(45)  # let the format settle to avoid segfaults on some styles
            sizes.append(win.editor.currentCharFormat().fontPointSize())
    assert len(sizes) >= 2 and all(
        a > b for a, b in zip(sizes, sizes[1:])
    ), f"Heading sizes not decreasing: {sizes}"

    win.toolBar.actCode.trigger()
    QTest.qWait(45)

    win.toolBar.actBullets.trigger()
    QTest.qWait(45)
    win.toolBar.actNumbers.trigger()
    QTest.qWait(45)

    win.toolBar.actAlignC.trigger()
    QTest.qWait(45)
    assert int(win.editor.alignment()) & int(Qt.AlignHCenter)
    win.toolBar.actAlignR.trigger()
    QTest.qWait(45)
    assert int(win.editor.alignment()) & int(Qt.AlignRight)
    win.toolBar.actAlignL.trigger()
    QTest.qWait(45)
    assert int(win.editor.alignment()) & int(Qt.AlignLeft)
