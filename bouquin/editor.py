from __future__ import annotations

from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QTextCharFormat,
    QTextListFormat,
    QTextBlockFormat,
)
from PySide6.QtCore import Slot
from PySide6.QtWidgets import QTextEdit


class Editor(QTextEdit):
    def __init__(self):
        super().__init__()
        tab_w = 4 * self.fontMetrics().horizontalAdvance(" ")
        self.setTabStopDistance(tab_w)

    def merge_on_sel(self, fmt):
        """
        Sets the styling on the selected characters.
        """
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.select(cursor.SelectionType.WordUnderCursor)
        cursor.mergeCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)

    @Slot()
    def apply_weight(self):
        cur = self.currentCharFormat()
        fmt = QTextCharFormat()
        weight = QFont.Weight.Normal if cur.fontWeight() == QFont.Weight.Bold else QFont.Weight.Bold
        fmt.setFontWeight(weight)
        self.merge_on_sel(fmt)

    @Slot()
    def apply_italic(self):
        cur = self.currentCharFormat()
        fmt = QTextCharFormat()
        fmt.setFontItalic(not cur.fontItalic())
        self.merge_on_sel(fmt)

    @Slot()
    def apply_underline(self):
        cur = self.currentCharFormat()
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not cur.fontUnderline())
        self.merge_on_sel(fmt)

    @Slot()
    def apply_strikethrough(self):
        cur = self.currentCharFormat()
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not cur.fontStrikeOut())
        self.merge_on_sel(fmt)

    @Slot()
    def apply_code(self):
        c = self.textCursor()
        if not c.hasSelection():
            c.select(c.SelectionType.BlockUnderCursor)

        bf = QTextBlockFormat()
        bf.setLeftMargin(12)
        bf.setRightMargin(12)
        bf.setTopMargin(6)
        bf.setBottomMargin(6)
        bf.setBackground(QColor(245, 245, 245))
        bf.setNonBreakableLines(True)

        cf = QTextCharFormat()
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        cf.setFont(mono)
        cf.setFontFixedPitch(True)

        # If the current block already looks like a code block, remove styling
        cur_bf = c.blockFormat()
        is_code = (
            cur_bf.nonBreakableLines()
            and cur_bf.background().color().rgb() == QColor(245, 245, 245).rgb()
        )
        if is_code:
            # clear: margins/background/wrapping
            bf = QTextBlockFormat()
            cf = QTextCharFormat()

        c.mergeBlockFormat(bf)
        c.mergeBlockCharFormat(cf)

    @Slot(int)
    def apply_heading(self, size):
        fmt = QTextCharFormat()
        if size:
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setFontPointSize(size)
        else:
            fmt.setFontWeight(QFont.Weight.Normal)
            fmt.setFontPointSize(self.font().pointSizeF())
        self.merge_on_sel(fmt)

    def toggle_bullets(self):
        c = self.textCursor()
        lst = c.currentList()
        if lst and lst.format().style() == QTextListFormat.Style.ListDisc:
            lst.remove(c.block())
            return
        fmt = QTextListFormat()
        fmt.setStyle(QTextListFormat.Style.ListDisc)
        c.createList(fmt)

    def toggle_numbers(self):
        c = self.textCursor()
        lst = c.currentList()
        if lst and lst.format().style() == QTextListFormat.Style.ListDecimal:
            lst.remove(c.block())
            return
        fmt = QTextListFormat()
        fmt.setStyle(QTextListFormat.Style.ListDecimal)
        c.createList(fmt)
