from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QDialogButtonBox,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QMessageBox,
    QWidget,
    QTabWidget,
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

        self.current_settings = load_db_config()

        self.setMinimumWidth(480)
        self.setSizeGripEnabled(True)

        # --- Tabs ----------------------------------------------------------
        tabs = QTabWidget()
        tabs.setTabPosition(QTabWidget.North)
        tabs.setDocumentMode(True)
        tabs.setMovable(False)

        tabs.addTab(self._create_appearance_page(cfg), strings._("appearance"))
        tabs.addTab(self._create_features_page(), strings._("features"))
        tabs.addTab(self._create_security_page(cfg), strings._("security"))
        tabs.addTab(self._create_database_page(), strings._("database"))

        # --- Buttons -------------------------------------------------------
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)

        # Root layout
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        root.addWidget(tabs)
        root.addWidget(bb, 0, Qt.AlignRight)

    # ------------------------------------------------------------------ #
    #  Pages
    # ------------------------------------------------------------------ #

    def _create_appearance_page(self, cfg: DBConfig) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # --- Theme group --------------------------------------------------
        theme_group = QGroupBox(strings._("theme"))
        theme_layout = QVBoxLayout(theme_group)

        self.theme_system = QRadioButton(strings._("system"))
        self.theme_light = QRadioButton(strings._("light"))
        self.theme_dark = QRadioButton(strings._("dark"))

        current_theme = self.current_settings.theme
        if current_theme == Theme.DARK.value:
            self.theme_dark.setChecked(True)
        elif current_theme == Theme.LIGHT.value:
            self.theme_light.setChecked(True)
        else:
            self.theme_system.setChecked(True)

        theme_layout.addWidget(self.theme_system)
        theme_layout.addWidget(self.theme_light)
        theme_layout.addWidget(self.theme_dark)

        # font size row
        font_row = QHBoxLayout()
        self.font_heading = QLabel(strings._("font_size"))
        self.font_size = QSpinBox()
        self.font_size.setRange(1, 24)
        self.font_size.setSingleStep(1)
        self.font_size.setAccelerated(True)
        self.font_size.setValue(getattr(cfg, "font_size", 11))
        font_row.addWidget(self.font_heading)
        font_row.addWidget(self.font_size)
        font_row.addStretch()
        theme_layout.addLayout(font_row)

        # explanation
        self.font_size_label = QLabel(strings._("font_size_explanation"))
        self.font_size_label.setWordWrap(True)
        self.font_size_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        pal = self.font_size_label.palette()
        self.font_size_label.setForegroundRole(QPalette.PlaceholderText)
        self.font_size_label.setPalette(pal)

        font_exp_row = QHBoxLayout()
        font_exp_row.setContentsMargins(24, 0, 0, 0)
        font_exp_row.addWidget(self.font_size_label)
        theme_layout.addLayout(font_exp_row)

        layout.addWidget(theme_group)

        # --- Locale group -------------------------------------------------
        locale_group = QGroupBox(strings._("locale"))
        locale_layout = QVBoxLayout(locale_group)

        self.locale_combobox = QComboBox()
        self.locale_combobox.addItems(strings._AVAILABLE)
        self.locale_combobox.setCurrentText(self.current_settings.locale)
        locale_layout.addWidget(self.locale_combobox, 0, Qt.AlignLeft)

        self.locale_label = QLabel(strings._("locale_restart"))
        self.locale_label.setWordWrap(True)
        self.locale_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        lpal = self.locale_label.palette()
        self.locale_label.setForegroundRole(QPalette.PlaceholderText)
        self.locale_label.setPalette(lpal)
        loc_row = QHBoxLayout()
        loc_row.setContentsMargins(24, 0, 0, 0)
        loc_row.addWidget(self.locale_label)
        locale_layout.addLayout(loc_row)

        layout.addWidget(locale_group)
        layout.addStretch()
        return page

    def _create_features_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        features_group = QGroupBox(strings._("features"))
        features_layout = QVBoxLayout(features_group)

        self.move_todos = QCheckBox(
            strings._("move_yesterdays_unchecked_todos_to_today_on_startup")
        )
        self.move_todos.setChecked(self.current_settings.move_todos)
        self.move_todos.setCursor(Qt.PointingHandCursor)
        features_layout.addWidget(self.move_todos)

        self.tags = QCheckBox(strings._("enable_tags_feature"))
        self.tags.setChecked(self.current_settings.tags)
        self.tags.setCursor(Qt.PointingHandCursor)
        features_layout.addWidget(self.tags)

        self.time_log = QCheckBox(strings._("enable_time_log_feature"))
        self.time_log.setChecked(self.current_settings.time_log)
        self.time_log.setCursor(Qt.PointingHandCursor)
        features_layout.addWidget(self.time_log)

        layout.addWidget(features_group)
        layout.addStretch()
        return page

    def _create_security_page(self, cfg: DBConfig) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # --- Encryption group ---------------------------------------------
        enc_group = QGroupBox(strings._("encryption"))
        enc = QVBoxLayout(enc_group)

        self.save_key_btn = QCheckBox(strings._("remember_key"))
        self.key = self.current_settings.key or ""
        self.save_key_btn.setChecked(bool(self.key))
        self.save_key_btn.setCursor(Qt.PointingHandCursor)
        self.save_key_btn.toggled.connect(self._save_key_btn_clicked)
        enc.addWidget(self.save_key_btn, 0, Qt.AlignLeft)

        self.save_key_label = QLabel(strings._("save_key_warning"))
        self.save_key_label.setWordWrap(True)
        self.save_key_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        pal = self.save_key_label.palette()
        self.save_key_label.setForegroundRole(QPalette.PlaceholderText)
        self.save_key_label.setPalette(pal)

        exp_row = QHBoxLayout()
        exp_row.setContentsMargins(24, 0, 0, 0)
        exp_row.addWidget(self.save_key_label)
        enc.addLayout(exp_row)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        enc.addWidget(line)

        self.rekey_btn = QPushButton(strings._("change_encryption_key"))
        self.rekey_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.rekey_btn.clicked.connect(self._change_key)
        enc.addWidget(self.rekey_btn, 0, Qt.AlignLeft)

        layout.addWidget(enc_group)

        # --- Idle lock group ----------------------------------------------
        priv_group = QGroupBox(strings._("lock_screen_when_idle"))
        priv = QVBoxLayout(priv_group)

        self.idle_spin = QSpinBox()
        self.idle_spin.setRange(0, 240)
        self.idle_spin.setSingleStep(1)
        self.idle_spin.setAccelerated(True)
        self.idle_spin.setSuffix(" min")
        self.idle_spin.setSpecialValueText(strings._("never"))
        self.idle_spin.setValue(getattr(cfg, "idle_minutes", 15))
        priv.addWidget(self.idle_spin, 0, Qt.AlignLeft)

        self.idle_spin_label = QLabel(strings._("autolock_explanation"))
        self.idle_spin_label.setWordWrap(True)
        self.idle_spin_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        spal = self.idle_spin_label.palette()
        self.idle_spin_label.setForegroundRole(QPalette.PlaceholderText)
        self.idle_spin_label.setPalette(spal)

        spin_row = QHBoxLayout()
        spin_row.setContentsMargins(24, 0, 0, 0)
        spin_row.addWidget(self.idle_spin_label)
        priv.addLayout(spin_row)

        layout.addWidget(priv_group)
        layout.addStretch()
        return page

    def _create_database_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        maint_group = QGroupBox(strings._("database_maintenance"))
        maint = QVBoxLayout(maint_group)

        self.compact_btn = QPushButton(strings._("database_compact"))
        self.compact_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.compact_btn.clicked.connect(self._compact_btn_clicked)
        maint.addWidget(self.compact_btn, 0, Qt.AlignLeft)

        self.compact_label = QLabel(strings._("database_compact_explanation"))
        self.compact_label.setWordWrap(True)
        self.compact_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        cpal = self.compact_label.palette()
        self.compact_label.setForegroundRole(QPalette.PlaceholderText)
        self.compact_label.setPalette(cpal)

        maint_row = QHBoxLayout()
        maint_row.setContentsMargins(24, 0, 0, 0)
        maint_row.addWidget(self.compact_label)
        maint.addLayout(maint_row)

        layout.addWidget(maint_group)
        layout.addStretch()
        return page

    # ------------------------------------------------------------------ #
    #  Save settings
    # ------------------------------------------------------------------ #

    def _save(self):
        if self.theme_dark.isChecked():
            selected_theme = Theme.DARK
        elif self.theme_light.isChecked():
            selected_theme = Theme.LIGHT
        else:
            selected_theme = Theme.SYSTEM

        key_to_save = self.key if self.save_key_btn.isChecked() else ""

        self._cfg = DBConfig(
            path=Path(self.current_settings.path),
            key=key_to_save,
            idle_minutes=self.idle_spin.value(),
            theme=selected_theme.value,
            move_todos=self.move_todos.isChecked(),
            tags=self.tags.isChecked(),
            time_log=self.time_log.isChecked(),
            locale=self.locale_combobox.currentText(),
            font_size=self.font_size.value(),
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
            QMessageBox.critical(self, strings._("error"), str(e))

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
            QMessageBox.critical(self, strings._("error"), str(e))

    @property
    def config(self) -> DBConfig:
        return self._cfg
