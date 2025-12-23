from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import strings
from .db import DBConfig, DBManager
from .key_prompt import KeyPrompt
from .settings import load_db_config, save_db_config
from .theme import Theme


class SettingsDialog(QDialog):
    def __init__(self, cfg: DBConfig, db: DBManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle(strings._("settings"))
        self._cfg = DBConfig(path=cfg.path, key="")
        self._db = db
        self.key = ""

        self.current_settings = load_db_config()

        self.setMinimumWidth(600)
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
            strings._("move_unchecked_todos_to_today_on_startup")
        )
        self.move_todos.setChecked(self.current_settings.move_todos)
        self.move_todos.setCursor(Qt.PointingHandCursor)
        features_layout.addWidget(self.move_todos)

        # Optional: allow moving to the very next day even if it is a weekend.
        self.move_todos_include_weekends = QCheckBox(
            strings._("move_todos_include_weekends")
        )
        self.move_todos_include_weekends.setChecked(
            getattr(self.current_settings, "move_todos_include_weekends", False)
        )
        self.move_todos_include_weekends.setCursor(Qt.PointingHandCursor)
        self.move_todos_include_weekends.setEnabled(self.move_todos.isChecked())

        move_todos_opts = QWidget()
        move_todos_opts_layout = QVBoxLayout(move_todos_opts)
        move_todos_opts_layout.setContentsMargins(24, 0, 0, 0)
        move_todos_opts_layout.setSpacing(4)
        move_todos_opts_layout.addWidget(self.move_todos_include_weekends)
        features_layout.addWidget(move_todos_opts)

        self.move_todos.toggled.connect(self.move_todos_include_weekends.setEnabled)

        self.tags = QCheckBox(strings._("enable_tags_feature"))
        self.tags.setChecked(self.current_settings.tags)
        self.tags.setCursor(Qt.PointingHandCursor)
        features_layout.addWidget(self.tags)

        self.time_log = QCheckBox(strings._("enable_time_log_feature"))
        self.time_log.setChecked(self.current_settings.time_log)
        self.time_log.setCursor(Qt.PointingHandCursor)
        features_layout.addWidget(self.time_log)

        self.invoicing = QCheckBox(strings._("enable_invoicing_feature"))
        invoicing_enabled = getattr(self.current_settings, "invoicing", False)
        self.invoicing.setChecked(invoicing_enabled and self.current_settings.time_log)
        self.invoicing.setCursor(Qt.PointingHandCursor)
        features_layout.addWidget(self.invoicing)
        # Invoicing only if time_log is enabled
        if not self.current_settings.time_log:
            self.invoicing.setChecked(False)
            self.invoicing.setEnabled(False)
        self.time_log.toggled.connect(self._on_time_log_toggled)

        # --- Reminders feature + webhook options -------------------------
        self.reminders = QCheckBox(strings._("enable_reminders_feature"))
        self.reminders.setChecked(self.current_settings.reminders)
        self.reminders.toggled.connect(self._on_reminders_toggled)
        self.reminders.setCursor(Qt.PointingHandCursor)
        features_layout.addWidget(self.reminders)

        # Container for reminder-specific options, indented under the checkbox
        self.reminders_options_container = QWidget()
        reminders_options_layout = QVBoxLayout(self.reminders_options_container)
        reminders_options_layout.setContentsMargins(24, 0, 0, 0)
        reminders_options_layout.setSpacing(4)

        self.reminders_options_toggle = QToolButton()
        self.reminders_options_toggle.setText(
            strings._("reminders_webhook_section_title")
        )
        self.reminders_options_toggle.setCheckable(True)
        self.reminders_options_toggle.setChecked(False)
        self.reminders_options_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.reminders_options_toggle.setArrowType(Qt.RightArrow)
        self.reminders_options_toggle.clicked.connect(
            self._on_reminders_options_toggled
        )

        toggle_row = QHBoxLayout()
        toggle_row.addWidget(self.reminders_options_toggle)
        toggle_row.addStretch()
        reminders_options_layout.addLayout(toggle_row)

        # Actual options (labels + QLineEdits)
        self.reminders_options_widget = QWidget()
        options_form = QFormLayout(self.reminders_options_widget)
        options_form.setContentsMargins(0, 0, 0, 0)
        options_form.setSpacing(4)

        self.reminders_webhook_url = QLineEdit(
            self.current_settings.reminders_webhook_url or ""
        )
        self.reminders_webhook_secret = QLineEdit(
            self.current_settings.reminders_webhook_secret or ""
        )
        self.reminders_webhook_secret.setEchoMode(QLineEdit.Password)

        options_form.addRow(
            strings._("reminders_webhook_url_label") + ":",
            self.reminders_webhook_url,
        )
        options_form.addRow(
            strings._("reminders_webhook_secret_label") + ":",
            self.reminders_webhook_secret,
        )

        reminders_options_layout.addWidget(self.reminders_options_widget)

        features_layout.addWidget(self.reminders_options_container)

        self.reminders_options_container.setVisible(self.reminders.isChecked())
        self.reminders_options_widget.setVisible(False)

        self.documents = QCheckBox(strings._("enable_documents_feature"))
        self.documents.setChecked(self.current_settings.documents)
        self.documents.setCursor(Qt.PointingHandCursor)
        features_layout.addWidget(self.documents)

        layout.addWidget(features_group)

        # --- Invoicing / company profile section -------------------------
        self.invoicing_group = QGroupBox(strings._("invoice_company_profile"))
        invoicing_layout = QFormLayout(self.invoicing_group)

        profile = self._db.get_company_profile() or (
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        name, address, phone, email, tax_id, payment_details, logo_bytes = profile

        self.company_name_edit = QLineEdit(name or "")
        self.company_address_edit = QTextEdit(address or "")
        self.company_phone_edit = QLineEdit(phone or "")
        self.company_email_edit = QLineEdit(email or "")
        self.company_tax_id_edit = QLineEdit(tax_id or "")
        self.company_payment_details_edit = QTextEdit()
        self.company_payment_details_edit.setPlainText(payment_details or "")

        invoicing_layout.addRow(
            strings._("invoice_company_name") + ":", self.company_name_edit
        )
        invoicing_layout.addRow(
            strings._("invoice_company_address") + ":", self.company_address_edit
        )
        invoicing_layout.addRow(
            strings._("invoice_company_phone") + ":", self.company_phone_edit
        )
        invoicing_layout.addRow(
            strings._("invoice_company_email") + ":", self.company_email_edit
        )
        invoicing_layout.addRow(
            strings._("invoice_company_tax_id") + ":", self.company_tax_id_edit
        )
        invoicing_layout.addRow(
            strings._("invoice_company_payment_details") + ":",
            self.company_payment_details_edit,
        )

        # Logo picker - store bytes on self._logo_bytes
        self._logo_bytes = logo_bytes
        logo_row = QHBoxLayout()
        self.logo_label = QLabel(strings._("invoice_company_logo_not_set"))
        if logo_bytes:
            self.logo_label.setText(strings._("invoice_company_logo_set"))
        logo_btn = QPushButton(strings._("invoice_company_logo_choose"))
        logo_btn.clicked.connect(self._on_choose_logo)
        logo_row.addWidget(self.logo_label)
        logo_row.addWidget(logo_btn)
        invoicing_layout.addRow(strings._("invoice_company_logo") + ":", logo_row)

        # Show/hide this whole block based on invoicing checkbox
        self.invoicing_group.setVisible(self.invoicing.isChecked())
        self.invoicing.toggled.connect(self.invoicing_group.setVisible)

        layout.addWidget(self.invoicing_group)

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
            move_todos_include_weekends=self.move_todos_include_weekends.isChecked(),
            tags=self.tags.isChecked(),
            time_log=self.time_log.isChecked(),
            reminders=self.reminders.isChecked(),
            reminders_webhook_url=self.reminders_webhook_url.text().strip() or None,
            reminders_webhook_secret=self.reminders_webhook_secret.text().strip()
            or None,
            documents=self.documents.isChecked(),
            invoicing=(
                self.invoicing.isChecked() if self.time_log.isChecked() else False
            ),
            locale=self.locale_combobox.currentText(),
            font_size=self.font_size.value(),
        )

        save_db_config(self._cfg)

        # Save company profile only if invoicing is enabled
        if self.invoicing.isChecked() and self.time_log.isChecked():
            self._db.save_company_profile(
                name=self.company_name_edit.text().strip() or None,
                address=self.company_address_edit.toPlainText().strip() or None,
                phone=self.company_phone_edit.text().strip() or None,
                email=self.company_email_edit.text().strip() or None,
                tax_id=self.company_tax_id_edit.text().strip() or None,
                payment_details=self.company_payment_details_edit.toPlainText().strip()
                or None,
                logo=getattr(self, "_logo_bytes", None),
            )

        self.parent().themes.set(selected_theme)
        self.accept()

    def _on_reminders_options_toggled(self, checked: bool) -> None:
        """
        Expand/collapse the advanced reminders options (webhook URL/secret).
        """
        if checked:
            self.reminders_options_toggle.setArrowType(Qt.DownArrow)
            self.reminders_options_widget.show()
        else:
            self.reminders_options_toggle.setArrowType(Qt.RightArrow)
            self.reminders_options_widget.hide()

    def _on_reminders_toggled(self, checked: bool) -> None:
        """
        Conditionally show reminder webhook options depending
        on if the reminders feature is toggled on or off.
        """
        if hasattr(self, "reminders_options_container"):
            self.reminders_options_container.setVisible(checked)

        # When turning reminders off, also collapse the section
        if not checked and hasattr(self, "reminders_options_toggle"):
            self.reminders_options_toggle.setChecked(False)
            self._on_reminders_options_toggled(False)

    def _on_time_log_toggled(self, checked: bool) -> None:
        """
        Enforce 'invoicing depends on time logging'.
        """
        if not checked:
            # Turn off + disable invoicing if time logging is disabled
            self.invoicing.setChecked(False)
            self.invoicing.setEnabled(False)
        else:
            # Let the user enable invoicing when time logging is enabled
            self.invoicing.setEnabled(True)

    def _on_choose_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            strings._("invoice_company_logo_choose"),
            "",
            "Images (*.png *.jpg *.jpeg *.bmp)",
        )
        if not path:
            return

        try:
            with open(path, "rb") as f:
                self._logo_bytes = f.read()
            self.logo_label.setText(Path(path).name)
        except OSError as exc:
            QMessageBox.warning(self, strings._("error"), str(exc))

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
