from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QPlainTextEdit,
    QDialogButtonBox,
    QComboBox,
    QLabel,
)

from . import strings


class CodeBlockEditorDialog(QDialog):
    def __init__(self, code: str, language: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(strings._("edit_code_block"))

        self.setMinimumSize(650, 650)
        self._code_edit = QPlainTextEdit(self)
        self._code_edit.setPlainText(code)

        # Language selector (optional)
        self._lang_combo = QComboBox(self)
        languages = [
            "",
            "bash",
            "css",
            "html",
            "javascript",
            "php",
            "python",
        ]
        self._lang_combo.addItems(languages)
        if language and language in languages:
            self._lang_combo.setCurrentText(language)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(strings._("locale") + ":", self))
        layout.addWidget(self._lang_combo)
        layout.addWidget(self._code_edit)
        layout.addWidget(buttons)

    def code(self) -> str:
        return self._code_edit.toPlainText()

    def language(self) -> str | None:
        text = self._lang_combo.currentText().strip()
        return text or None
