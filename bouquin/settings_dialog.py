from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from . import strings


class SettingsDialog(QDialog):
    def __init__(self, cfg: DBConfig, db: DBManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle(strings._("settings"))
        self._cfg = DBConfig(path=cfg.path, key="")
        self._db = db
        self.key = ""

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.setMinimumWidth(560)
        self.setSizeGripEnabled(True)

        current_settings = load_db_config()

        # Add theme selection
        theme_group = QGroupBox(strings._("theme"))
        theme_layout = QVBoxLayout(theme_group)

        self.theme_system = QRadioButton(strings._("system"))
        self.theme_light = QRadioButton(strings._("light"))
        self.theme_dark = QRadioButton(strings._("dark"))

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

        # Locale settings
        locale_group = QGroupBox(strings._("locale"))
        locale_layout = QVBoxLayout(locale_group)
        locale_layout.setContentsMargins(12, 8, 12, 12)
        locale_layout.setSpacing(6)

        self.locale_combobox = QComboBox()
        self.locale_combobox.addItems(strings._AVAILABLE)
        self.locale_combobox.setCurrentText(current_settings.locale)
        locale_layout.addWidget(self.locale_combobox, 0, Qt.AlignLeft)

        # Explanation for locale
        self.locale_label = QLabel(strings._("locale_restart"))
        self.locale_label.setWordWrap(True)
        self.locale_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        # make it look secondary
        lpal = self.locale_label.palette()
        self.locale_label.setForegroundRole(QPalette.PlaceholderText)
        self.locale_label.setPalette(lpal)
        locale_row = QHBoxLayout()
        locale_row.setContentsMargins(24, 0, 0, 0)
        locale_row.addWidget(self.locale_label)
        locale_layout.addLayout(locale_row)
        form.addRow(locale_group)

        # Add Behaviour
        behaviour_group = QGroupBox(strings._("behaviour"))
        behaviour_layout = QVBoxLayout(behaviour_group)

        self.move_todos = QCheckBox(
            strings._("move_yesterdays_unchecked_todos_to_today_on_startup")
        )
        self.move_todos.setChecked(current_settings.move_todos)
        self.move_todos.setCursor(Qt.PointingHandCursor)

        behaviour_layout.addWidget(self.move_todos)
        form.addRow(behaviour_group)

        self.path_edit = QLineEdit(str(self._cfg.path))
        self.path_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        browse_btn = QPushButton(strings._("browse"))
        browse_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        browse_btn.clicked.connect(self._browse)
        path_row = QWidget()
        h = QHBoxLayout(path_row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.path_edit, 1)
        h.addWidget(browse_btn, 0)
        h.setStretch(0, 1)
        h.setStretch(1, 0)
        form.addRow(strings._("database_path"), path_row)

        # Encryption settings
        enc_group = QGroupBox(strings._("encryption"))
        enc = QVBoxLayout(enc_group)
        enc.setContentsMargins(12, 8, 12, 12)
        enc.setSpacing(6)

        # Checkbox to remember key
        self.save_key_btn = QCheckBox(strings._("remember_key"))
        self.key = current_settings.key or ""
        self.save_key_btn.setChecked(bool(self.key))
        self.save_key_btn.setCursor(Qt.PointingHandCursor)
        self.save_key_btn.toggled.connect(self._save_key_btn_clicked)
        enc.addWidget(self.save_key_btn, 0, Qt.AlignLeft)

        # Explanation for remembering key
        self.save_key_label = QLabel(strings._("save_key_warning"))
        self.save_key_label.setWordWrap(True)
        self.save_key_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        # make it look secondary
        pal = self.save_key_label.palette()
        self.save_key_label.setForegroundRole(QPalette.PlaceholderText)
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
        self.rekey_btn = QPushButton(strings._("change_encryption_key"))
        self.rekey_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.rekey_btn.clicked.connect(self._change_key)

        enc.addWidget(self.rekey_btn, 0, Qt.AlignLeft)

        form.addRow(enc_group)

        # Privacy settings
        priv_group = QGroupBox(strings._("lock_screen_when_idle"))
        priv = QVBoxLayout(priv_group)
        priv.setContentsMargins(12, 8, 12, 12)
        priv.setSpacing(6)

        self.idle_spin = QSpinBox()
        self.idle_spin.setRange(0, 240)
        self.idle_spin.setSingleStep(1)
        self.idle_spin.setAccelerated(True)
        self.idle_spin.setSuffix(" min")
        self.idle_spin.setSpecialValueText(strings._("Never"))
        self.idle_spin.setValue(getattr(cfg, "idle_minutes", 15))
        priv.addWidget(self.idle_spin, 0, Qt.AlignLeft)
        # Explanation for idle option (autolock)
        self.idle_spin_label = QLabel(strings._("autolock_explanation"))
        self.idle_spin_label.setWordWrap(True)
        self.idle_spin_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        # make it look secondary
        spal = self.idle_spin_label.palette()
        self.idle_spin_label.setForegroundRole(QPalette.PlaceholderText)
        self.idle_spin_label.setPalette(spal)

        spin_row = QHBoxLayout()
        spin_row.setContentsMargins(24, 0, 0, 0)  # indent to line up under the spinbox
        spin_row.addWidget(self.idle_spin_label)
        priv.addLayout(spin_row)

        form.addRow(priv_group)

        # Maintenance settings
        maint_group = QGroupBox(strings._("database_maintenance"))
        maint = QVBoxLayout(maint_group)
        maint.setContentsMargins(12, 8, 12, 12)
        maint.setSpacing(6)

        self.compact_btn = QPushButton(strings._("database_compact"))
        self.compact_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.compact_btn.clicked.connect(self._compact_btn_clicked)

        maint.addWidget(self.compact_btn, 0, Qt.AlignLeft)

        # Explanation for compacting button
        self.compact_label = QLabel(strings._("database_compact_explanation"))
        self.compact_label.setWordWrap(True)
        self.compact_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        # make it look secondary
        cpal = self.compact_label.palette()
        self.compact_label.setForegroundRole(QPalette.PlaceholderText)
        self.compact_label.setPalette(cpal)

        maint_row = QHBoxLayout()
        maint_row.setContentsMargins(24, 0, 0, 0)
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
            strings._("database_path"),
            self.path_edit.text(),
            "(*.db);;(*)",
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
            locale=self.locale_combobox.currentText(),
        )

        save_db_config(self._cfg)
        self.parent().themes.set(selected_theme)
        self.accept()

    def _change_key(self):
        p1 = KeyPrompt(
            self,
            title=strings._("change_encryption_key"),
            message=strings._("enter_a_new_encryption_key"),
        )
        if p1.exec() != QDialog.Accepted:
            return
        new_key = p1.key()
        p2 = KeyPrompt(
            self,
            title=strings._("change_encryption_key"),
            message=strings._("reenter_the_new_key"),
        )
        if p2.exec() != QDialog.Accepted:
            return
        if new_key != p2.key():
            QMessageBox.warning(
                self, strings._("key_mismatch"), strings._("key_mismatch_explanation")
            )
            return
        if not new_key:
            QMessageBox.warning(
                self, strings._("empty_key"), strings._("empty_key_explanation")
            )
            return
        try:
            self.key = new_key
            self._db.rekey(new_key)
            QMessageBox.information(
                self, strings._("key_changed"), strings._("key_changed_explanation")
            )
        except Exception as e:
            QMessageBox.critical(self, strings._("error"), e)

    @Slot(bool)
    def _save_key_btn_clicked(self, checked: bool):
        self.key = ""
        if checked:
            if not self.key:
                p1 = KeyPrompt(
                    self,
                    title=strings._("unlock_encrypted_notebook_explanation"),
                    message=strings._("unlock_encrypted_notebook_explanation"),
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
                self, strings._("success"), strings._("database_compacted_successfully")
            )
        except Exception as e:
            QMessageBox.critical(self, strings._("error"), e)

    @property
    def config(self) -> DBConfig:
        return self._cfg
