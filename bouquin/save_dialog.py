from __future__ import annotations

import datetime

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QDialogButtonBox,
)


class SaveDialog(QDialog):
    def __init__(
        self,
        parent=None,
        title: str = "Enter a name for this version",
        message: str = "Enter a name for this version?",
    ):
        """
        Used for explicitly saving a new version of a page.
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(message))
        self.note = QLineEdit()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.note.setText(f"New version I saved at {now}")
        v.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def note_text(self) -> str:
        return self.note.text()
