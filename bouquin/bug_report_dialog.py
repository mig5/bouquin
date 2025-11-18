from __future__ import annotations

import importlib.metadata

import requests

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QTextEdit,
    QDialogButtonBox,
    QMessageBox,
)

from . import strings


BUG_REPORT_HOST = "https://nr.mig5.net"
ROUTE = "forms/bouquin/bugs"


class BugReportDialog(QDialog):
    """
    Dialog to collect a bug report
    """

    MAX_CHARS = 5000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(strings._("report_a_bug"))

        layout = QVBoxLayout(self)

        header = QLabel(strings._("bug_report_explanation"))
        header.setWordWrap(True)
        layout.addWidget(header)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(strings._("bug_report_placeholder"))
        layout.addWidget(self.text_edit)

        self.text_edit.textChanged.connect(self._enforce_max_length)

        # Buttons: Cancel / Send
        button_box = QDialogButtonBox(QDialogButtonBox.Cancel)
        button_box.addButton(strings._("send"), QDialogButtonBox.AcceptRole)
        button_box.accepted.connect(self._send)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setMinimumWidth(560)

        self.text_edit.setFocus()

    # ------------Helpers ------------ #

    def _enforce_max_length(self):
        text = self.text_edit.toPlainText()
        if len(text) <= self.MAX_CHARS:
            return

        # Remember cursor position
        cursor = self.text_edit.textCursor()
        pos = cursor.position()

        # Trim and restore without re-entering this slot
        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText(text[: self.MAX_CHARS])
        self.text_edit.blockSignals(False)

        # Clamp cursor position to end of text
        if pos > self.MAX_CHARS:
            pos = self.MAX_CHARS

        cursor.setPosition(pos)
        self.text_edit.setTextCursor(cursor)

    def _send(self):
        text = self.text_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(
                self,
                strings._("report_a_bug"),
                strings._("bug_report_empty"),
            )
            return

        # Get current app version
        try:
            version = importlib.metadata.version("bouquin")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"

        payload: dict[str, str] = {
            "message": text,
            "version": version,
        }

        # POST as JSON
        try:
            resp = requests.post(
                f"{BUG_REPORT_HOST}/{ROUTE}",
                json=payload,
                timeout=10,
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                strings._("report_a_bug"),
                strings._("bug_report_send_failed") + f"\n{e}",
            )
            return

        if resp.status_code == 201:
            QMessageBox.information(
                self,
                strings._("report_a_bug"),
                strings._("bug_report_sent_ok"),
            )
            self.accept()
        else:
            QMessageBox.critical(
                self,
                strings._("report_a_bug"),
                strings._("bug_report_send_failed") + f" (HTTP {resp.status_code})",
            )
