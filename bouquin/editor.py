from __future__ import annotations

from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QTextCharFormat,
    QTextCursor,
    QTextListFormat,
    QTextBlockFormat,
)
from PySide6.QtCore import Qt, QUrl, Signal, Slot, QRegularExpression
from PySide6.QtWidgets import QTextEdit

from .url_highlighter import UrlHighlighter

class Editor(QTextEdit):
    linkActivated = Signal(str)

    _URL_RX = QRegularExpression(r"(https?://[^\s<>\"]+|www\.[^\s<>\"]+)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tab_w = 4 * self.fontMetrics().horizontalAdvance(" ")
        self.setTabStopDistance(tab_w)

        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextEditorInteraction
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )

        self.setAcceptRichText(True)

        # Turn raw URLs into anchors
        self._linkifying = False
        self.textChanged.connect(self._linkify_document)
        self.viewport().setMouseTracking(True)

    def _linkify_document(self):
        if self._linkifying:
            return
        self._linkifying = True

        doc = self.document()
        cur = QTextCursor(doc)
        cur.beginEditBlock()

        block = doc.begin()
        while block.isValid():
            text = block.text()
            it = self._URL_RX.globalMatch(text)
            while it.hasNext():
                m = it.next()
                start = block.position() + m.capturedStart()
                end   = start + m.capturedLength()

                cur.setPosition(start)
                cur.setPosition(end, QTextCursor.KeepAnchor)

                fmt = cur.charFormat()
                if fmt.isAnchor():   # already linkified; skip
                    continue

                href = m.captured(0)
                if href.startswith("www."):
                    href = "https://" + href

                fmt.setAnchor(True)
                # Qt 6: use setAnchorHref; for compatibility, also set names.
                try:
                    fmt.setAnchorHref(href)
                except AttributeError:
                    fmt.setAnchorNames([href])

                fmt.setFontUnderline(True)
                fmt.setForeground(Qt.blue)
                cur.setCharFormat(fmt)

            block = block.next()

        cur.endEditBlock()
        self._linkifying = False

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and (e.modifiers() & Qt.ControlModifier):
            href = self.anchorAt(e.pos())
            if href:
                QDesktopServices.openUrl(QUrl.fromUserInput(href))
                self.linkActivated.emit(href)
                return
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        if (e.modifiers() & Qt.ControlModifier) and self.anchorAt(e.pos()):
            self.viewport().setCursor(Qt.PointingHandCursor)
        else:
            self.viewport().setCursor(Qt.IBeamCursor)
        super().mouseMoveEvent(e)

    def keyPressEvent(self, e):
        key = e.key()

        # Pre-insert: stop link/format bleed for “word boundary” keys
        if key in (Qt.Key_Space, Qt.Key_Tab):
            self._break_anchor_for_next_char()
            return super().keyPressEvent(e)

        # When pressing Enter/return key, insert first, then neutralise the empty block’s inline format
        if key in (Qt.Key_Return, Qt.Key_Enter):
            super().keyPressEvent(e) # create the new (possibly empty) paragraph

            # If we're on an empty block, clear the insertion char format so the
            # *next* Enter will create another new line (not consume the press to reset formatting).
            c = self.textCursor()
            block = c.block()
            if block.length() == 1:
                self._clear_insertion_char_format()
            return

        return super().keyPressEvent(e)

    def _clear_insertion_char_format(self):
        """Reset inline typing format (keeps lists, alignment, margins, etc.)."""
        nf = QTextCharFormat()
        self.setCurrentCharFormat(nf)

    def _break_anchor_for_next_char(self):
        c = self.textCursor()
        fmt = c.charFormat()
        if fmt.isAnchor() or fmt.fontUnderline() or fmt.foreground().style() != 0:
            # clone, then strip just the link-specific bits so the next char is plain text
            nf = QTextCharFormat(fmt)
            nf.setAnchor(False)
            nf.setFontUnderline(False)
            nf.clearForeground()
            try:
                nf.setAnchorHref("")
            except AttributeError:
                nf.setAnchorNames([])
            self.setCurrentCharFormat(nf)

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
