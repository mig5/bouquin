from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QDialogButtonBox,
    QSizePolicy,
    QMessageBox,
)

from .db import DBConfig, DBManager
from .settings import save_db_config
from .key_prompt import KeyPrompt


class SettingsDialog(QDialog):
    def __init__(self, cfg: DBConfig, db: DBManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._cfg = DBConfig(path=cfg.path, key="")
        self._db = db

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.setMinimumWidth(520)
        self.setSizeGripEnabled(True)

        self.path_edit = QLineEdit(str(self._cfg.path))
        self.path_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        browse_btn = QPushButton("Browse…")
        browse_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        browse_btn.clicked.connect(self._browse)
        path_row = QWidget()
        h = QHBoxLayout(path_row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.path_edit, 1)
        h.addWidget(browse_btn, 0)
        h.setStretch(0, 1)
        h.setStretch(1, 0)
        form.addRow("Database path", path_row)

        # Change key button
        self.rekey_btn = QPushButton("Change key")
        self.rekey_btn.clicked.connect(self._change_key)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)

        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addWidget(self.rekey_btn)
        v.addWidget(bb)

    def _browse(self):
        p, _ = QFileDialog.getSaveFileName(
            self,
            "Choose database file",
            self.path_edit.text(),
            "DB Files (*.db);;All Files (*)",
        )
        if p:
            self.path_edit.setText(p)

    def _save(self):
        self._cfg = DBConfig(path=Path(self.path_edit.text()), key="")
        save_db_config(self._cfg)
        self.accept()

    def _change_key(self):
        p1 = KeyPrompt(self, title="Change key", message="Enter new key")
        if p1.exec() != QDialog.Accepted:
            return
        new_key = p1.key()
        p2 = KeyPrompt(self, title="Change key", message="Re-enter new key")
        if p2.exec() != QDialog.Accepted:
            return
        if new_key != p2.key():
            QMessageBox.warning(self, "Key mismatch", "The two entries did not match.")
            return
        if not new_key:
            QMessageBox.warning(self, "Empty key", "Key cannot be empty.")
            return
        try:
            self._db.rekey(new_key)
            QMessageBox.information(
                self, "Key changed", "The database key was updated."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not change key:\n{e}")

    @property
    def config(self) -> DBConfig:
        return self._cfg
