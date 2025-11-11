from __future__ import annotations

import re

from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QPalette,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)

from .theme import ThemeManager, Theme


class MarkdownHighlighter(QSyntaxHighlighter):
    """Live syntax highlighter for markdown that applies formatting as you type."""

    def __init__(self, document: QTextDocument, theme_manager: ThemeManager):
        super().__init__(document)
        self.theme_manager = theme_manager
        self._setup_formats()
        # Recompute formats whenever the app theme changes
        self.theme_manager.themeChanged.connect(self._on_theme_changed)

    def _on_theme_changed(self, *_):
        self._setup_formats()
        self.rehighlight()

    def _setup_formats(self):
        """Setup text formats for different markdown elements."""

        # Bold: **text** or __text__
        self.bold_format = QTextCharFormat()
        self.bold_format.setFontWeight(QFont.Weight.Bold)

        # Italic: *text* or _text_
        self.italic_format = QTextCharFormat()
        self.italic_format.setFontItalic(True)

        # Strikethrough: ~~text~~
        self.strike_format = QTextCharFormat()
        self.strike_format.setFontStrikeOut(True)

        # Allow combination of bold/italic
        self.bold_italic_format = QTextCharFormat()
        self.bold_italic_format.setFontWeight(QFont.Weight.Bold)
        self.bold_italic_format.setFontItalic(True)

        # Inline code: `code`
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.code_format = QTextCharFormat()
        self.code_format.setFont(mono)
        self.code_format.setFontFixedPitch(True)

        # Code block: ```
        self.code_block_format = QTextCharFormat()
        self.code_block_format.setFont(mono)
        self.code_block_format.setFontFixedPitch(True)

        pal = QGuiApplication.palette()
        if (
            self.theme_manager.current() == Theme.DARK
            or self.theme_manager._is_system_dark
        ):
            # In dark mode, use a darker panel-like background
            bg = pal.color(QPalette.AlternateBase)
            fg = pal.color(QPalette.Text)
        else:
            # Light mode: keep the existing light gray
            bg = QColor(245, 245, 245)
            fg = QColor(
                0, 0, 0
            )  # avoiding using QPalette.Text as it can be white on macOS
        self.code_block_format.setBackground(bg)
        self.code_block_format.setForeground(fg)

        # Headings
        self.h1_format = QTextCharFormat()
        self.h1_format.setFontPointSize(24.0)
        self.h1_format.setFontWeight(QFont.Weight.Bold)

        self.h2_format = QTextCharFormat()
        self.h2_format.setFontPointSize(18.0)
        self.h2_format.setFontWeight(QFont.Weight.Bold)

        self.h3_format = QTextCharFormat()
        self.h3_format.setFontPointSize(14.0)
        self.h3_format.setFontWeight(QFont.Weight.Bold)

        # Markdown syntax (the markers themselves) - make invisible
        self.syntax_format = QTextCharFormat()
        # Make the markers invisible by setting font size to 0.1 points
        self.syntax_format.setFontPointSize(0.1)
        # Also make them very faint in case they still show
        self.syntax_format.setForeground(QColor(250, 250, 250))

    def _overlay_range(
        self, start: int, length: int, overlay_fmt: QTextCharFormat
    ) -> None:
        """Merge overlay_fmt onto the existing format for each char in [start, start+length)."""
        end = start + length
        i = start
        while i < end:
            base = QTextCharFormat(self.format(i))  # current format at this position
            base.merge(overlay_fmt)  # add only the properties we set
            self.setFormat(i, 1, base)  # write back one char
            i += 1

    def highlightBlock(self, text: str):
        """Apply formatting to a block of text based on markdown syntax."""

        # Track if we're in a code block (multiline)
        prev_state = self.previousBlockState()
        in_code_block = prev_state == 1

        # Check for code block fences
        if text.strip().startswith("```"):
            # background for the whole fence line (so block looks continuous)
            self.setFormat(0, len(text), self.code_block_format)

            # hide the three backticks themselves
            idx = text.find("```")
            if idx != -1:
                self.setFormat(idx, 3, self.syntax_format)

            # toggle code-block state and stop; next line picks up state
            in_code_block = not in_code_block
            self.setCurrentBlockState(1 if in_code_block else 0)
            return

        if in_code_block:
            # inside code: apply block bg and language rules
            self.setFormat(0, len(text), self.code_block_format)
            self.setCurrentBlockState(1)
            return

        # ---- Normal markdown (outside code)
        self.setCurrentBlockState(0)

        # If the line is empty and not in a code block, nothing else to do
        if not text:
            return

        # Headings (must be at start of line)
        heading_match = re.match(r"^(#{1,3})\s+", text)
        if heading_match:
            level = len(heading_match.group(1))
            marker_len = len(heading_match.group(0))

            # Format the # markers
            self.setFormat(0, marker_len, self.syntax_format)

            # Format the heading text
            heading_fmt = (
                self.h1_format
                if level == 1
                else self.h2_format if level == 2 else self.h3_format
            )
            self.setFormat(marker_len, len(text) - marker_len, heading_fmt)
            return

        # Bold+Italic: ***text*** or ___text___
        # Do these first and remember their spans so later passes don't override them.
        occupied = []
        for m in re.finditer(
            r"(?<!\*)\*\*\*(.+?)(?<!\*)\*\*\*|(?<!_)___(.+?)(?<!_)___", text
        ):
            start, end = m.span()
            content_start, content_end = start + 3, end - 3
            self.setFormat(start, 3, self.syntax_format)  # hide leading ***
            self.setFormat(end - 3, 3, self.syntax_format)  # hide trailing ***
            self.setFormat(
                content_start, content_end - content_start, self.bold_italic_format
            )
            occupied.append((start, end))

        def _overlaps(a, b):
            return not (a[1] <= b[0] or b[1] <= a[0])

        # Bold: **text** or __text__ (but not part of *** or ___)
        for m in re.finditer(
            r"(?<!\*)\*\*(?!\*)(.+?)(?<!\*)\*\*(?!\*)|(?<!_)__(?!_)(.+?)(?<!_)__(?!_)",
            text,
        ):
            start, end = m.span()
            if any(_overlaps((start, end), occ) for occ in occupied):
                continue
            content_start, content_end = start + 2, end - 2
            self.setFormat(start, 2, self.syntax_format)
            self.setFormat(end - 2, 2, self.syntax_format)
            self.setFormat(content_start, content_end - content_start, self.bold_format)

        # Italic: *text* or _text_ (but not part of bold/** and not inside *** or ___)
        for m in re.finditer(
            r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", text
        ):
            start, end = m.span()
            if any(_overlaps((start, end), occ) for occ in occupied):
                continue
            # Keep your existing guards that avoid grabbing * from **:
            if start > 0 and text[start - 1 : start + 1] in ("**", "__"):
                continue
            if end < len(text) and text[end : end + 1] in ("*", "_"):
                continue
            content_start, content_end = start + 1, end - 1
            self.setFormat(start, 1, self.syntax_format)
            self.setFormat(end - 1, 1, self.syntax_format)
            self.setFormat(
                content_start, content_end - content_start, self.italic_format
            )

        # Strikethrough: ~~text~~
        for m in re.finditer(r"~~(.+?)~~", text):
            start, end = m.span()
            content_start, content_end = start + 2, end - 2
            # Fade the markers
            self.setFormat(start, 2, self.syntax_format)
            self.setFormat(end - 2, 2, self.syntax_format)
            # Merge strikeout with whatever is already applied (bold, italic, both, links, etc.)
            self._overlay_range(
                content_start, content_end - content_start, self.strike_format
            )

        # Inline code: `code`
        for match in re.finditer(r"`([^`]+)`", text):
            start, end = match.span()
            content_start = start + 1
            content_end = end - 1

            self.setFormat(start, 1, self.syntax_format)
            self.setFormat(end - 1, 1, self.syntax_format)
            self.setFormat(content_start, content_end - content_start, self.code_format)
