from __future__ import annotations

import re
from typing import Iterable, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import strings

Row = Tuple[str, str, str, str, str | None]


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
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return

        kind = data.get("kind")
        if kind == "page":
            date_iso = data.get("date")
            if date_iso:
                self.openDateRequested.emit(date_iso)
        elif kind == "document":
            doc_id = data.get("doc_id")
            file_name = data.get("file_name") or "document"
            if doc_id is None:
                return
            self._open_document(int(doc_id), file_name)

    def _open_document(self, doc_id: int, file_name: str) -> None:
        """Open the selected document in the user's default app."""
        from bouquin.document_utils import open_document_from_db

        open_document_from_db(self._db, doc_id, file_name, parent_widget=self)

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

        # Only highlight calendar dates for page results
        page_dates = sorted(
            {key for (kind, key, _title, _text, _aux) in rows if kind == "page"}
        )
        self.resultDatesChanged.emit(page_dates)
        self.results.show()

        for kind, key, title, text, aux in rows:
            # Build an HTML fragment around the match
            frag_html = self._make_html_snippet(text, query, radius=30, maxlen=90)

            container = QWidget()
            outer = QVBoxLayout(container)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(2)

            # ---- Heading (date for pages, "Document" for docs) ----
            heading = QLabel(title)
            heading.setStyleSheet("font-weight:bold;")
            outer.addWidget(heading)

            # ---- Preview row ----
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

            # Separator line
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            outer.addWidget(line)

            # ---- Add to list ----
            item = QListWidgetItem()
            if kind == "page":
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    {"kind": "page", "date": key},
                )
            else:  # document
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    {
                        "kind": "document",
                        "doc_id": int(key),
                        "file_name": aux or "",
                    },
                )

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
