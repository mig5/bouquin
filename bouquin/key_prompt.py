from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QDialogButtonBox,
    QFileDialog,
)

from . import strings


class KeyPrompt(QDialog):
    def __init__(
        self,
        parent=None,
        title: str = strings._("key_prompt_enter_key"),
        message: str = strings._("key_prompt_enter_key"),
        initial_db_path: str | Path | None = None,
        show_db_change: bool = False,
    ):
        """
        Prompt the user for the key required to decrypt the database.

        Used when opening the app, unlocking the idle locked screen,
        or when rekeying.

        If show_db_change is true, also show a QFileDialog allowing to
        select a database file, else the default from settings is used.
        """
        super().__init__(parent)
        self.setWindowTitle(title)

        self._db_path: Path | None = Path(initial_db_path) if initial_db_path else None

        v = QVBoxLayout(self)

        v.addWidget(QLabel(message))

        # DB chooser
        self.path_edit: QLineEdit | None = None
        if show_db_change:
            path_row = QHBoxLayout()
            self.path_edit = QLineEdit()
            if self._db_path is not None:
                self.path_edit.setText(str(self._db_path))

            browse_btn = QPushButton(strings._("select_notebook"))

            def _browse():
                start_dir = str(self._db_path or "")
                fname, _ = QFileDialog.getOpenFileName(
                    self,
                    strings._("select_notebook"),
                    start_dir,
                    "SQLCipher DB (*.db);;All files (*)",
                )
                if fname:
                    self._db_path = Path(fname)
                    if self.path_edit is not None:
                        self.path_edit.setText(fname)

            browse_btn.clicked.connect(_browse)

            path_row.addWidget(self.path_edit, 1)
            path_row.addWidget(browse_btn)
            v.addLayout(path_row)

        # Key entry
        self.key_entry = QLineEdit()
        self.key_entry.setEchoMode(QLineEdit.Password)
        v.addWidget(self.key_entry)

        toggle = QPushButton(strings._("show"))
        toggle.setCheckable(True)
        toggle.toggled.connect(
            lambda c: self.key_entry.setEchoMode(
                QLineEdit.Normal if c else QLineEdit.Password
            )
        )
        v.addWidget(toggle)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        self.key_entry.setFocus()
        self.resize(500, self.sizeHint().height())

    def key(self) -> str:
        return self.key_entry.text()

    def db_path(self) -> Path | None:
        """Return the chosen DB path (or None if unchanged/not shown)."""
        if self.path_edit is not None:
            text = self.path_edit.text().strip()
            if text:
                return Path(text)
        return self._db_path
