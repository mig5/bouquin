from __future__ import annotations

import datetime

from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout

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
        text = strings._("new_version_i_saved_at") + f" {now}"
        self.note.setText(text)
        v.addWidget(self.note)

        # make dialog wide enough for the line edit text
        fm = QFontMetrics(self.note.font())
        text_width = fm.horizontalAdvance(text) + 20
        self.note.setMinimumWidth(text_width)
        self.adjustSize()

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def note_text(self) -> str:
        return self.note.text()
