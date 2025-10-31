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
)

from .db import DBConfig
from .settings import save_db_config


class SettingsDialog(QDialog):
    def __init__(self, cfg: DBConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._cfg = DBConfig(path=cfg.path, key="")

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

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)

        v = QVBoxLayout(self)
        v.addLayout(form)
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

    @property
    def config(self) -> DBConfig:
        return self._cfg
