from __future__ import annotations

import re
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat
from PySide6.QtCore import Qt, QRegularExpression

class UrlHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self.rx = QRegularExpression(r"(https?://[^\s<>\"]+|www\.[^\s<>\"]+)")

    def highlightBlock(self, text: str):
        it = self.rx.globalMatch(text)
        while it.hasNext():
            m = it.next()
            href = m.captured(0)
            if href.startswith("www."):
                href = "https://" + href

            fmt = QTextCharFormat()
            fmt.setAnchor(True)
            fmt.setAnchorHref(href)
            fmt.setFontUnderline(True)
            fmt.setForeground(Qt.blue)
            self.setFormat(m.capturedStart(0), m.capturedLength(0), fmt)
