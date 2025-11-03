from __future__ import annotations

from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QTextCharFormat,
    QTextCursor,
    QTextFrameFormat,
    QTextListFormat,
    QTextBlockFormat,
)
from PySide6.QtCore import Qt, QUrl, Signal, Slot, QRegularExpression
from PySide6.QtWidgets import QTextEdit


class Editor(QTextEdit):
    linkActivated = Signal(str)

    _URL_RX = QRegularExpression(r'((?:https?://|www\.)[^\s<>"\'<>]+)')
    _CODE_BG = QColor(245, 245, 245)
    _CODE_FRAME_PROP = int(QTextFrameFormat.UserProperty) + 100  # marker for our frames

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

    def _find_code_frame(self, cursor=None):
        """Return the nearest ancestor frame that's one of our code frames, else None."""
        if cursor is None:
            cursor = self.textCursor()
        f = cursor.currentFrame()
        while f:
            if f.frameFormat().property(self._CODE_FRAME_PROP):
                return f
            f = f.parentFrame()
        return None

    def _is_code_block(self, block) -> bool:
        if not block.isValid():
            return False
        bf = block.blockFormat()
        return bool(
            bf.nonBreakableLines()
            and bf.background().color().rgb() == self._CODE_BG.rgb()
        )

    def _trim_url_end(self, url: str) -> str:
        # strip common trailing punctuation not part of the URL
        trimmed = url.rstrip(".,;:!?\"'")
        # drop an unmatched closing ) or ] at the very end
        if trimmed.endswith(")") and trimmed.count("(") < trimmed.count(")"):
            trimmed = trimmed[:-1]
        if trimmed.endswith("]") and trimmed.count("[") < trimmed.count("]"):
            trimmed = trimmed[:-1]
        return trimmed

    def _linkify_document(self):
        if self._linkifying:
            return
        self._linkifying = True

        try:
            block = self.textCursor().block()
            start_pos = block.position()
            text = block.text()

            cur = QTextCursor(self.document())
            cur.beginEditBlock()

            it = self._URL_RX.globalMatch(text)
            while it.hasNext():
                m = it.next()
                s = start_pos + m.capturedStart()
                raw = m.captured(0)
                url = self._trim_url_end(raw)
                if not url:
                    continue

                e = s + len(url)
                cur.setPosition(s)
                cur.setPosition(e, QTextCursor.KeepAnchor)

                if url.startswith("www."):
                    href = "https://" + url
                else:
                    href = url

                fmt = QTextCharFormat()
                fmt.setAnchor(True)
                fmt.setAnchorHref(href)  # always refresh to the latest full URL
                fmt.setFontUnderline(True)
                fmt.setForeground(Qt.blue)

                cur.mergeCharFormat(fmt)  # merge so we don’t clobber other styling

            cur.endEditBlock()
        finally:
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

        if key in (Qt.Key_Return, Qt.Key_Enter):
            c = self.textCursor()
            # If we're on an empty line inside a code frame, consume Enter and jump out
            if c.block().length() == 1:
                frame = self._find_code_frame(c)
                if frame:
                    out = QTextCursor(self.document())
                    out.setPosition(frame.lastPosition())  # after the frame's contents
                    self.setTextCursor(out)
                    super().insertPlainText("\n")  # start a normal paragraph
                    return

        # otherwise default handling
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
        weight = (
            QFont.Weight.Normal
            if cur.fontWeight() == QFont.Weight.Bold
            else QFont.Weight.Bold
        )
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
            c.select(QTextCursor.BlockUnderCursor)

        # Wrap the selection in a single frame (no per-block padding/margins).
        ff = QTextFrameFormat()
        ff.setBackground(self._CODE_BG)
        ff.setPadding(6)  # visual padding for the WHOLE block
        ff.setBorder(0)
        ff.setLeftMargin(0)
        ff.setRightMargin(0)
        ff.setTopMargin(0)
        ff.setBottomMargin(0)
        ff.setProperty(self._CODE_FRAME_PROP, True)

        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)

        c.beginEditBlock()
        try:
            c.insertFrame(ff)  # with a selection, this wraps the selection

            # Format all blocks inside the new frame: zero vertical margins, mono font, no wrapping
            frame = self._find_code_frame(c)
            bc = QTextCursor(self.document())
            bc.setPosition(frame.firstPosition())

            while bc.position() < frame.lastPosition():
                bc.select(QTextCursor.BlockUnderCursor)

                bf = QTextBlockFormat()
                bf.setTopMargin(0)
                bf.setBottomMargin(0)
                bf.setLeftMargin(12)
                bf.setRightMargin(12)
                bf.setNonBreakableLines(True)

                cf = QTextCharFormat()
                cf.setFont(mono)
                cf.setFontFixedPitch(True)

                bc.mergeBlockFormat(bf)
                bc.mergeBlockCharFormat(cf)

                bc.setPosition(bc.block().position() + bc.block().length())
        finally:
            c.endEditBlock()

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
