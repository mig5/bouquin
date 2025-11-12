from __future__ import annotations

import re
from typing import Iterable, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from . import strings

Row = Tuple[str, str]


class Search(QWidget):
    """Encapsulates the search UI + logic and emits a signal when a result is chosen."""

    openDateRequested = Signal(str)
    resultDatesChanged = Signal(list)

    def __init__(self, db, parent: QWidget | None = None):
        super().__init__(parent)
        self._db = db

        self.search = QLineEdit()
        self.search.setPlaceholderText(strings._("search_for_notes_here"))
        self.search.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.search.textChanged.connect(self._search)

        self.results = QListWidget()
        self.results.setUniformItemSizes(False)
        self.results.setSelectionMode(self.results.SelectionMode.SingleSelection)
        self.results.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.results.itemClicked.connect(self._open_selected)
        self.results.hide()
        self.results.setMinimumHeight(250)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignTop)
        lay.addWidget(self.search)
        lay.addWidget(self.results)

    def _open_selected(self, item: QListWidgetItem):
        date_str = item.data(Qt.ItemDataRole.UserRole)
        if date_str:
            self.openDateRequested.emit(date_str)

    def _search(self, text: str):
        """
        Search for the supplied text in the database.
        For all rows found, populate the results widget with a clickable preview.
        """
        q = text.strip()
        if not q:
            self.results.clear()
            self.results.hide()
            self.resultDatesChanged.emit([])  # clear highlights
            return

        rows: Iterable[Row] = self._db.search_entries(q)

        self._populate_results(q, rows)

    def _populate_results(self, query: str, rows: Iterable[Row]):
        self.results.clear()
        rows = list(rows)
        if not rows:
            self.results.hide()
            self.resultDatesChanged.emit([])  # clear highlights
            return

        self.resultDatesChanged.emit(sorted({d for d, _ in rows}))
        self.results.show()

        for date_str, content in rows:
            # Build an HTML fragment around the match and whether to show ellipses
            frag_html = self._make_html_snippet(content, query, radius=30, maxlen=90)
            # ---- Per-item widget: date on top, preview row below (with ellipses) ----
            container = QWidget()
            outer = QVBoxLayout(container)
            outer.setContentsMargins(8, 6, 8, 6)
            outer.setSpacing(2)

            # Date label (plain text)
            date_lbl = QLabel()
            date_lbl.setTextFormat(Qt.TextFormat.RichText)
            date_lbl.setText(f"<h3><i>{date_str}</i></h3>")
            date_f = date_lbl.font()
            date_f.setPointSizeF(date_f.pointSizeF() + 1)
            date_lbl.setFont(date_f)
            outer.addWidget(date_lbl)

            # Preview row with optional ellipses
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)

            preview = QLabel()
            preview.setTextFormat(Qt.TextFormat.RichText)
            preview.setWordWrap(True)
            preview.setOpenExternalLinks(True)
            preview.setText(
                frag_html
                if frag_html
                else "<span style='color:#888'>(no preview)</span>"
            )
            h.addWidget(preview, 1)

            outer.addWidget(row)

            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            outer.addWidget(line)

            # ---- Add to list ----
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, date_str)
            item.setSizeHint(container.sizeHint())

            self.results.addItem(item)
            self.results.setItemWidget(item, container)

    # --- Snippet/highlight helpers -----------------------------------------
    def _make_html_snippet(self, markdown_src: str, query: str, radius=60, maxlen=180):
        # For markdown, we can work directly with the text
        # Strip markdown formatting for display
        plain = self._strip_markdown(markdown_src)
        if not plain:
            return "", False, False

        tokens = [t for t in re.split(r"\s+", query.strip()) if t]
        L = len(plain)

        # Find first occurrence (phrase first, then earliest token)
        idx, mlen = -1, 0
        if tokens:
            lower = plain.lower()
            phrase = " ".join(tokens).lower()
            j = lower.find(phrase)
            if j >= 0:
                idx, mlen = j, len(phrase)
            else:
                for t in tokens:
                    tj = lower.find(t.lower())
                    if tj >= 0 and (idx < 0 or tj < idx):
                        idx, mlen = tj, len(t)
        # Compute window
        if idx < 0:
            start, end = 0, min(L, maxlen)
        else:
            start = max(0, min(idx - radius, max(0, L - maxlen)))
            end = min(L, max(idx + mlen + radius, start + maxlen))

        # Extract snippet and highlight matches
        snippet = plain[start:end]

        # Escape HTML and bold matches
        import html as _html

        snippet_html = _html.escape(snippet)
        if tokens:
            for t in tokens:
                # Case-insensitive replacement
                pattern = re.compile(re.escape(t), re.IGNORECASE)
                snippet_html = pattern.sub(
                    lambda m: f"<b>{m.group(0)}</b>", snippet_html
                )

        return snippet_html

    def _strip_markdown(self, markdown: str) -> str:
        """Strip markdown formatting for plain text display."""
        # Remove images
        text = re.sub(r"!\[.*?\]\(.*?\)", "[Image]", markdown)
        # Remove links but keep text
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        # Remove inline code backticks
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # Remove bold/italic markers
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"_([^_]+)_", r"\1", text)
        # Remove strikethrough
        text = re.sub(r"~~([^~]+)~~", r"\1", text)
        # Remove heading markers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Remove list markers
        text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
        # Remove checkbox markers
        text = re.sub(r"^\s*-\s*\[[x ☐☑]\]\s+", "", text, flags=re.MULTILINE)
        # Remove code block fences
        text = re.sub(r"```[^\n]*\n", "", text)
        return text.strip()
