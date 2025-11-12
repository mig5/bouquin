from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QDialogButtonBox,
)

from . import strings


class KeyPrompt(QDialog):
    def __init__(
        self,
        parent=None,
        title: str = strings._("key_prompt_enter_key"),
        message: str = strings._("key_prompt_enter_key"),
    ):
        """
        Prompt the user for the key required to decrypt the database.

        Used when opening the app, unlocking the idle locked screen,
        or when rekeying.
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(message))
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        v.addWidget(self.edit)
        toggle = QPushButton(strings._("show"))
        toggle.setCheckable(True)
        toggle.toggled.connect(
            lambda c: self.edit.setEchoMode(
                QLineEdit.Normal if c else QLineEdit.Password
            )
        )
        v.addWidget(toggle)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def key(self) -> str:
        return self.edit.text()
