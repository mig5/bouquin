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
    def __init__(
        self, code: str, language: str | None, parent=None, allow_delete: bool = False
    ):
        super().__init__(parent)
        self.setWindowTitle(strings._("edit_code_block"))

        self.setMinimumSize(650, 650)
        self._code_edit = QPlainTextEdit(self)
        self._code_edit.setPlainText(code)

        # Track whether the user clicked "Delete"
        self._delete_requested = False

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

        if allow_delete:
            delete_btn = buttons.addButton(
                strings._("delete_code_block"),
                QDialogButtonBox.ButtonRole.DestructiveRole,
            )
            delete_btn.clicked.connect(self._on_delete_clicked)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(strings._("locale") + ":", self))
        layout.addWidget(self._lang_combo)
        layout.addWidget(self._code_edit)
        layout.addWidget(buttons)

    def _on_delete_clicked(self) -> None:
        """Mark this dialog as 'delete requested' and close as Accepted."""
        self._delete_requested = True
        self.accept()

    def was_deleted(self) -> bool:
        """Return True if the user chose to delete the code block."""
        return self._delete_requested

    def code(self) -> str:
        return self._code_edit.toPlainText()

    def language(self) -> str | None:
        text = self._lang_combo.currentText().strip()
        return text or None
