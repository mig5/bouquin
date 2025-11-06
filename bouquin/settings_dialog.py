from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QDialogButtonBox,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QMessageBox,
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPalette


from .db import DBConfig, DBManager
from .settings import load_db_config, save_db_config
from .theme import Theme
from .key_prompt import KeyPrompt


class SettingsDialog(QDialog):
    def __init__(self, cfg: DBConfig, db: DBManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._cfg = DBConfig(path=cfg.path, key="")
        self._db = db
        self.key = ""

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.setMinimumWidth(560)
        self.setSizeGripEnabled(True)

        current_settings = load_db_config()

        # Add theme selection
        theme_group = QGroupBox("Theme")
        theme_layout = QVBoxLayout(theme_group)

        self.theme_system = QRadioButton("System")
        self.theme_light = QRadioButton("Light")
        self.theme_dark = QRadioButton("Dark")

        # Load current theme from settings
        current_theme = current_settings.theme
        if current_theme == Theme.DARK.value:
            self.theme_dark.setChecked(True)
        elif current_theme == Theme.LIGHT.value:
            self.theme_light.setChecked(True)
        else:
            self.theme_system.setChecked(True)

        theme_layout.addWidget(self.theme_system)
        theme_layout.addWidget(self.theme_light)
        theme_layout.addWidget(self.theme_dark)

        form.addRow(theme_group)

        # Add Behaviour
        behaviour_group = QGroupBox("Behaviour")
        behaviour_layout = QVBoxLayout(behaviour_group)

        self.move_todos = QCheckBox(
            "Move yesterday's unchecked TODOs to today on startup"
        )
        self.move_todos.setChecked(current_settings.move_todos)
        self.move_todos.setCursor(Qt.PointingHandCursor)

        behaviour_layout.addWidget(self.move_todos)
        form.addRow(behaviour_group)

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

        # Encryption settings
        enc_group = QGroupBox("Encryption")
        enc = QVBoxLayout(enc_group)
        enc.setContentsMargins(12, 8, 12, 12)
        enc.setSpacing(6)

        # Checkbox to remember key
        self.save_key_btn = QCheckBox("Remember key")
        self.key = current_settings.key or ""
        self.save_key_btn.setChecked(bool(self.key))
        self.save_key_btn.setCursor(Qt.PointingHandCursor)
        self.save_key_btn.toggled.connect(self._save_key_btn_clicked)
        enc.addWidget(self.save_key_btn, 0, Qt.AlignLeft)

        # Explanation for remembering key
        self.save_key_label = QLabel(
            "If you don't want to be prompted for your encryption key, check this to remember it. "
            "WARNING: the key is saved to disk and could be recoverable if your disk is compromised."
        )
        self.save_key_label.setWordWrap(True)
        self.save_key_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        # make it look secondary
        pal = self.save_key_label.palette()
        pal.setColor(self.save_key_label.foregroundRole(), pal.color(QPalette.Mid))
        self.save_key_label.setPalette(pal)

        exp_row = QHBoxLayout()
        exp_row.setContentsMargins(24, 0, 0, 0)  # indent to line up under the checkbox
        exp_row.addWidget(self.save_key_label)
        enc.addLayout(exp_row)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        enc.addWidget(line)

        # Change key button
        self.rekey_btn = QPushButton("Change encryption key")
        self.rekey_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.rekey_btn.clicked.connect(self._change_key)

        enc.addWidget(self.rekey_btn, 0, Qt.AlignLeft)

        form.addRow(enc_group)

        # Privacy settings
        priv_group = QGroupBox("Lock screen when idle")
        priv = QVBoxLayout(priv_group)
        priv.setContentsMargins(12, 8, 12, 12)
        priv.setSpacing(6)

        self.idle_spin = QSpinBox()
        self.idle_spin.setRange(0, 240)
        self.idle_spin.setSingleStep(1)
        self.idle_spin.setAccelerated(True)
        self.idle_spin.setSuffix(" min")
        self.idle_spin.setSpecialValueText("Never")
        self.idle_spin.setValue(getattr(cfg, "idle_minutes", 15))
        priv.addWidget(self.idle_spin, 0, Qt.AlignLeft)
        # Explanation for idle option (autolock)
        self.idle_spin_label = QLabel(
            "Bouquin will automatically lock the notepad after this length of time, after which you'll need to re-enter the key to unlock it. "
            "Set to 0 (never) to never lock."
        )
        self.idle_spin_label.setWordWrap(True)
        self.idle_spin_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        # make it look secondary
        spal = self.idle_spin_label.palette()
        spal.setColor(self.idle_spin_label.foregroundRole(), spal.color(QPalette.Mid))
        self.idle_spin_label.setPalette(spal)

        spin_row = QHBoxLayout()
        spin_row.setContentsMargins(24, 0, 0, 0)  # indent to line up under the spinbox
        spin_row.addWidget(self.idle_spin_label)
        priv.addLayout(spin_row)

        form.addRow(priv_group)

        # Maintenance settings
        maint_group = QGroupBox("Database maintenance")
        maint = QVBoxLayout(maint_group)
        maint.setContentsMargins(12, 8, 12, 12)
        maint.setSpacing(6)

        self.compact_btn = QPushButton("Compact database")
        self.compact_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.compact_btn.clicked.connect(self._compact_btn_clicked)

        maint.addWidget(self.compact_btn, 0, Qt.AlignLeft)

        # Explanation for compating button
        self.compact_label = QLabel(
            "Compacting runs VACUUM on the database. This can help reduce its size."
        )
        self.compact_label.setWordWrap(True)
        self.compact_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        # make it look secondary
        cpal = self.compact_label.palette()
        cpal.setColor(self.compact_label.foregroundRole(), cpal.color(QPalette.Mid))
        self.compact_label.setPalette(cpal)

        maint_row = QHBoxLayout()
        maint_row.setContentsMargins(24, 0, 0, 0)  # indent to line up under the button
        maint_row.addWidget(self.compact_label)
        maint.addLayout(maint_row)

        form.addRow(maint_group)

        # Buttons
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)

        # Root layout (adjust margins/spacing a bit)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addLayout(form)
        v.addWidget(bb, 0, Qt.AlignRight)

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
        # Save the selected theme into QSettings
        if self.theme_dark.isChecked():
            selected_theme = Theme.DARK
        elif self.theme_light.isChecked():
            selected_theme = Theme.LIGHT
        else:
            selected_theme = Theme.SYSTEM

        key_to_save = self.key if self.save_key_btn.isChecked() else ""

        self._cfg = DBConfig(
            path=Path(self.path_edit.text()),
            key=key_to_save,
            idle_minutes=self.idle_spin.value(),
            theme=selected_theme.value,
            move_todos=self.move_todos.isChecked(),
        )

        save_db_config(self._cfg)
        self.parent().themes.set(selected_theme)
        self.accept()

    def _change_key(self):
        p1 = KeyPrompt(self, title="Change key", message="Enter a new encryption key")
        if p1.exec() != QDialog.Accepted:
            return
        new_key = p1.key()
        p2 = KeyPrompt(self, title="Change key", message="Re-enter the new key")
        if p2.exec() != QDialog.Accepted:
            return
        if new_key != p2.key():
            QMessageBox.warning(self, "Key mismatch", "The two entries did not match.")
            return
        if not new_key:
            QMessageBox.warning(self, "Empty key", "Key cannot be empty.")
            return
        try:
            self.key = new_key
            self._db.rekey(new_key)
            QMessageBox.information(
                self, "Key changed", "The notebook was re-encrypted with the new key!"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not change key:\n{e}")

    @Slot(bool)
    def _save_key_btn_clicked(self, checked: bool):
        self.key = ""
        if checked:
            if not self.key:
                p1 = KeyPrompt(
                    self, title="Enter your key", message="Enter the encryption key"
                )
                if p1.exec() != QDialog.Accepted:
                    self.save_key_btn.blockSignals(True)
                    self.save_key_btn.setChecked(False)
                    self.save_key_btn.blockSignals(False)
                    return
                self.key = p1.key() or ""

    @Slot(bool)
    def _compact_btn_clicked(self):
        try:
            self._db.compact()
            QMessageBox.information(
                self, "Compact complete", "Database compacted successfully!"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not compact database:\n{e}")

    @property
    def config(self) -> DBConfig:
        return self._cfg
