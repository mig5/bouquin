from __future__ import annotations

import re
from PySide6.QtGui import QFont, QTextCharFormat, QSyntaxHighlighter, QColor


class MarkdownHighlighter(QSyntaxHighlighter):
    ST_NORMAL = 0
    ST_CODE = 1

    FENCE = re.compile(r"^```")

    def __init__(self, document):
        super().__init__(document)

        base_size = document.defaultFont().pointSizeF() or 12.0

        # Monospace for code
        self.mono = QFont("Monospace")
        self.mono.setStyleHint(QFont.TypeWriter)

        # Light, high-contrast scheme for code
        self.col_bg = QColor("#eef2f6")  # light code bg
        self.col_fg = QColor("#1f2328")  # dark text

        # Formats
        self.fmt_h = [QTextCharFormat() for _ in range(6)]
        for i, f in enumerate(self.fmt_h, start=1):
            f.setFontWeight(QFont.Weight.Bold)
            f.setFontPointSize(base_size + (7 - i))
        self.fmt_bold = QTextCharFormat()
        self.fmt_bold.setFontWeight(QFont.Weight.Bold)
        self.fmt_italic = QTextCharFormat()
        self.fmt_italic.setFontItalic(True)
        self.fmt_quote = QTextCharFormat()
        self.fmt_quote.setForeground(QColor("#6a737d"))
        self.fmt_link = QTextCharFormat()
        self.fmt_link.setFontUnderline(True)
        self.fmt_list = QTextCharFormat()
        self.fmt_list.setFontWeight(QFont.Weight.DemiBold)
        self.fmt_strike = QTextCharFormat()
        self.fmt_strike.setFontStrikeOut(True)

        # Uniform code style
        self.fmt_code = QTextCharFormat()
        self.fmt_code.setFont(self.mono)
        self.fmt_code.setFontPointSize(max(6.0, base_size - 1))
        self.fmt_code.setBackground(self.col_bg)
        self.fmt_code.setForeground(self.col_fg)

        # Simple patterns
        self.re_heading = re.compile(r"^(#{1,6}) +.*$")
        self.re_bold = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
        self.re_italic = re.compile(r"\*(?!\*)(.+?)\*|_(?!_)(.+?)_")
        self.re_strike = re.compile(r"~~(.+?)~~")
        self.re_inline_code = re.compile(r"`([^`]+)`")
        self.re_link = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
        self.re_list = re.compile(r"^ *(?:[-*+] +|[0-9]+[.)] +)")
        self.re_quote = re.compile(r"^> ?.*$")

    def highlightBlock(self, text: str) -> None:
        prev = self.previousBlockState()
        in_code = prev == self.ST_CODE

        if in_code:
            # Entire line is code
            self.setFormat(0, len(text), self.fmt_code)
            if self.FENCE.match(text):
                self.setCurrentBlockState(self.ST_NORMAL)
            else:
                self.setCurrentBlockState(self.ST_CODE)
            return

        # Starting/ending a fenced block?
        if self.FENCE.match(text):
            self.setFormat(0, len(text), self.fmt_code)
            self.setCurrentBlockState(self.ST_CODE)
            return

        # --- Normal markdown styling ---
        m = self.re_heading.match(text)
        if m:
            level = min(len(m.group(1)), 6)
            self.setFormat(0, len(text), self.fmt_h[level - 1])
            self.setCurrentBlockState(self.ST_NORMAL)
            return

        m = self.re_list.match(text)
        if m:
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_list)

        if self.re_quote.match(text):
            self.setFormat(0, len(text), self.fmt_quote)

        for m in self.re_inline_code.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_code)

        for m in self.re_bold.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_bold)

        for m in self.re_italic.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_italic)

        for m in self.re_strike.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_strike)

        for m in self.re_link.finditer(text):
            start = m.start(1) - 1
            length = len(m.group(1)) + 2
            self.setFormat(start, length, self.fmt_link)

        self.setCurrentBlockState(self.ST_NORMAL)
