from __future__ import annotations

import datetime

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QDialogButtonBox,
)

from . import strings


class SaveDialog(QDialog):
    def __init__(
        self,
        parent=None,
    ):
        """
        Used for explicitly saving a new version of a page.
        """
        super().__init__(parent)
        self.setWindowTitle(strings._("enter_a_name_for_this_version"))
        v = QVBoxLayout(self)
        v.addWidget(QLabel(strings._("enter_a_name_for_this_version")))
        self.note = QLineEdit()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.note.setText(strings._("new_version_i_saved_at") + f" {now}")
        v.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def note_text(self) -> str:
        return self.note.text()
