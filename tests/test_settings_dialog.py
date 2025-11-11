import pytest
import bouquin.settings_dialog as sd

from bouquin.db import DBManager, DBConfig
from bouquin.key_prompt import KeyPrompt
from bouquin.settings_dialog import SettingsDialog
from bouquin.theme import ThemeManager, ThemeConfig, Theme
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget


@pytest.mark.gui
def test_settings_dialog_config_roundtrip(qtbot, tmp_db_cfg, fresh_db, tmp_path):
    # Provide a parent that exposes a real ThemeManager (dialog calls parent().themes.set(...))
    app = QApplication.instance()
    parent = QWidget()
    parent.themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    dlg = SettingsDialog(tmp_db_cfg, fresh_db, parent=parent)
    qtbot.addWidget(dlg)
    dlg.show()

    dlg.path_edit.setText(str(tmp_path / "alt.db"))
    dlg.idle_spin.setValue(3)
    dlg.theme_light.setChecked(True)
    dlg.move_todos.setChecked(True)

    # Auto-accept the modal QMessageBox that _compact_btn_clicked() shows
    def _auto_accept_msgbox():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QMessageBox):
                w.accept()

    QTimer.singleShot(0, _auto_accept_msgbox)
    dlg._compact_btn_clicked()
    qtbot.wait(50)

    dlg._save()
    cfg = dlg.config
    assert cfg.path.name == "alt.db"
    assert cfg.idle_minutes == 3
    assert cfg.theme in ("light", "dark", "system")


def test_save_key_toggle_roundtrip(qtbot, tmp_db_cfg, fresh_db, app):
    parent = QWidget()
    parent.themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))

    dlg = SettingsDialog(tmp_db_cfg, fresh_db, parent=parent)
    qtbot.addWidget(dlg)
    dlg.show()

    # Ensure a clean starting state (suite may leave settings toggled on)
    dlg.save_key_btn.setChecked(False)
    dlg.key = ""

    # Robust popup pump so we never miss late dialogs
    def _pump():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, KeyPrompt):
                w.edit.setText("supersecret")
                w.accept()
            elif isinstance(w, QMessageBox):
                w.accept()

    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(_pump)
    timer.start()
    try:
        dlg.save_key_btn.setChecked(True)
        qtbot.waitUntil(lambda: dlg.key == "supersecret", timeout=1000)
        assert dlg.save_key_btn.isChecked()

        dlg.save_key_btn.setChecked(False)
        qtbot.waitUntil(lambda: dlg.key == "", timeout=1000)
        assert dlg.key == ""
    finally:
        timer.stop()


def test_change_key_mismatch_shows_error(qtbot, tmp_db_cfg, tmp_path, app):
    cfg = DBConfig(
        path=tmp_path / "iso.db",
        key="oldkey",
        idle_minutes=0,
        theme="light",
        move_todos=True,
    )
    db = DBManager(cfg)
    assert db.connect()
    db.save_new_version("2000-01-01", "seed", "seed")

    parent = QWidget()
    parent.themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    dlg = SettingsDialog(cfg, db, parent=parent)
    qtbot.addWidget(dlg)
    dlg.show()

    keys = ["one", "two"]

    def _pump_popups():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, KeyPrompt):
                w.edit.setText(keys.pop(0) if keys else "zzz")
                w.accept()
            elif isinstance(w, QMessageBox):
                w.accept()

    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(_pump_popups)
    timer.start()
    try:
        dlg._change_key()
    finally:
        timer.stop()
    db.close()
    db2 = DBManager(cfg)
    assert db2.connect()
    db2.close()


def test_change_key_success(qtbot, tmp_path, app):
    cfg = DBConfig(
        path=tmp_path / "iso2.db",
        key="oldkey",
        idle_minutes=0,
        theme="light",
        move_todos=True,
    )
    db = DBManager(cfg)
    assert db.connect()
    db.save_new_version("2001-01-01", "seed", "seed")

    parent = QWidget()
    parent.themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    dlg = SettingsDialog(cfg, db, parent=parent)
    qtbot.addWidget(dlg)
    dlg.show()

    keys = ["newkey", "newkey"]

    def _pump():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, KeyPrompt):
                w.edit.setText(keys.pop(0) if keys else "newkey")
                w.accept()
            elif isinstance(w, QMessageBox):
                w.accept()

    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(_pump)
    timer.start()
    try:
        dlg._change_key()
    finally:
        timer.stop()
    qtbot.wait(50)

    db.close()
    cfg.key = "newkey"
    db2 = DBManager(cfg)
    assert db2.connect()
    assert "seed" in db2.get_entry("2001-01-01")
    db2.close()


def test_settings_compact_error(qtbot, app, monkeypatch, tmp_db_cfg, fresh_db):
    # Parent with ThemeManager (dialog uses parent().themes.set(...))
    parent = QWidget()
    parent.themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    dlg = SettingsDialog(tmp_db_cfg, fresh_db, parent=parent)
    qtbot.addWidget(dlg)
    dlg.show()

    # Monkeypatch db.compact to raise
    def boom():
        raise RuntimeError("nope")

    dlg._db.compact = boom  # type: ignore

    called = {"critical": False, "title": None, "text": None}

    class DummyMB:
        @staticmethod
        def information(*args, **kwargs):
            return 0

        @staticmethod
        def critical(parent, title, text, *rest):
            called["critical"] = True
            called["title"] = title
            called["text"] = str(text)
            return 0

    # Swap QMessageBox used inside the dialog module so signature mismatch can't occur
    monkeypatch.setattr(sd, "QMessageBox", DummyMB, raising=True)

    # Invoke
    dlg._compact_btn_clicked()

    assert called["critical"]
    assert called["title"]
    assert called["text"]


@pytest.mark.gui
def test_settings_browse_sets_path(qtbot, app, tmp_path, fresh_db, monkeypatch):
    parent = QWidget()
    parent.themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    cfg = DBConfig(
        path=tmp_path / "x.db", key="k", idle_minutes=0, theme="light", move_todos=True
    )
    dlg = SettingsDialog(cfg, fresh_db, parent=parent)
    qtbot.addWidget(dlg)
    dlg.show()

    p = tmp_path / "new_file.db"
    monkeypatch.setattr(
        sd.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(p), "DB Files (*.db)")),
        raising=False,
    )
    dlg._browse()
    assert dlg.path_edit.text().endswith("new_file.db")
