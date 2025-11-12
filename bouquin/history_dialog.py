from __future__ import annotations

import difflib, re, html as _html
from datetime import datetime
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QMessageBox,
    QTextBrowser,
    QTabWidget,
)

from . import strings


def _markdown_to_text(s: str) -> str:
    """Convert markdown to plain text for diff comparison."""
    # Remove images
    s = re.sub(r"!\[.*?\]\(.*?\)", "[ Image ]", s)
    # Remove inline code formatting
    s = re.sub(r"`([^`]+)`", r"\1", s)
    # Remove bold/italic markers
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = re.sub(r"_([^_]+)_", r"\1", s)
    # Remove strikethrough
    s = re.sub(r"~~([^~]+)~~", r"\1", s)
    # Remove heading markers
    s = re.sub(r"^#{1,6}\s+", "", s, flags=re.MULTILINE)
    # Remove list markers
    s = re.sub(r"^\s*[-*+]\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*\d+\.\s+", "", s, flags=re.MULTILINE)
    # Remove checkbox markers
    s = re.sub(r"^\s*-\s*\[[x ☐☑]\]\s+", "", s, flags=re.MULTILINE)
    return s.strip()


def _colored_unified_diff_html(old_md: str, new_md: str) -> str:
    """Return HTML with colored unified diff (+ green, - red, context gray)."""
    a = _markdown_to_text(old_md).splitlines()
    b = _markdown_to_text(new_md).splitlines()
    ud = difflib.unified_diff(
        a, b, fromfile=strings._("current"), tofile=strings._("selected"), lineterm=""
    )
    lines = []
    for line in ud:
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(
                f"<span style='color:#116329'>+ {_html.escape(line[1:])}</span>"
            )
        elif line.startswith("-") and not line.startswith("---"):
            lines.append(
                f"<span style='color:#b31d28'>- {_html.escape(line[1:])}</span>"
            )
        elif line.startswith("@@"):
            lines.append(f"<span style='color:#6f42c1'>{_html.escape(line)}</span>")
        else:
            lines.append(f"<span style='color:#586069'>{_html.escape(line)}</span>")
    css = "pre { font-family: Consolas,Menlo,Monaco,monospace; font-size: 13px; }"
    return f"<style>{css}</style><pre>{'<br>'.join(lines)}</pre>"


class HistoryDialog(QDialog):
    """Show versions for a date, preview, diff, and allow revert."""

    def __init__(self, db, date_iso: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{strings._('history')} — {date_iso}")
        self._db = db
        self._date = date_iso
        self._versions = []  # list[dict] from DB
        self._current_id = None  # id of current

        root = QVBoxLayout(self)

        # Top: list of versions
        top = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumSize(500, 650)
        self.list.currentItemChanged.connect(self._on_select)
        top.addWidget(self.list, 1)

        # Right: tabs (Preview / Diff)
        self.tabs = QTabWidget()
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        self.diff = QTextBrowser()
        self.diff.setOpenExternalLinks(False)
        self.tabs.addTab(self.preview, strings._("history_dialog_preview"))
        self.tabs.addTab(self.diff, strings._("history_dialog_diff"))
        self.tabs.setMinimumSize(500, 650)
        top.addWidget(self.tabs, 2)

        root.addLayout(top)

        # Buttons
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_revert = QPushButton(strings._("history_dialog_revert_to_selected"))
        self.btn_revert.clicked.connect(self._revert)
        self.btn_close = QPushButton(strings._("close"))
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_revert)
        row.addWidget(self.btn_close)
        root.addLayout(row)

        self._load_versions()

    # --- Data/UX helpers ---
    def _load_versions(self):
        # [{id,version_no,created_at,note,is_current}]
        self._versions = self._db.list_versions(self._date)

        self._current_id = next(
            (v["id"] for v in self._versions if v["is_current"]), None
        )
        self.list.clear()
        for v in self._versions:
            created_at = datetime.fromisoformat(
                v["created_at"].replace("Z", "+00:00")
            ).astimezone()
            created_at_local = created_at.strftime("%Y-%m-%d %H:%M:%S %Z")
            label = f"v{v['version_no']} — {created_at_local}"
            if v.get("note"):
                label += f"  ·  {v['note']}"
            if v["is_current"]:
                label += "  **(" + strings._("current") + ")**"
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, v["id"])
            self.list.addItem(it)
        # select the first non-current if available, else current
        idx = 0
        for i, v in enumerate(self._versions):
            if not v["is_current"]:
                idx = i
                break
        if self.list.count():
            self.list.setCurrentRow(idx)

    @Slot()
    def _on_select(self):
        item = self.list.currentItem()
        if not item:
            self.preview.clear()
            self.diff.clear()
            self.btn_revert.setEnabled(False)
            return
        sel_id = item.data(Qt.UserRole)
        sel = self._db.get_version(version_id=sel_id)
        self.preview.setMarkdown(sel["content"])
        # Diff vs current (textual diff)
        cur = self._db.get_version(version_id=self._current_id)
        self.diff.setHtml(_colored_unified_diff_html(cur["content"], sel["content"]))
        # Enable revert only if selecting a non-current version
        self.btn_revert.setEnabled(sel_id != self._current_id)

    @Slot()
    def _revert(self):
        item = self.list.currentItem()
        if not item:
            return
        sel_id = item.data(Qt.UserRole)
        if sel_id == self._current_id:
            return
        # Flip head pointer to the older version
        try:
            self._db.revert_to_version(self._date, version_id=sel_id)
        except Exception as e:
            QMessageBox.critical(
                self, strings._("history_dialog_revert_failed"), str(e)
            )
            return
        self.accept()
