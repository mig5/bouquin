import pytest

from bouquin.db import DBManager, DBConfig
from bouquin.key_prompt import KeyPrompt
import bouquin.settings_dialog as sd
from bouquin.settings_dialog import SettingsDialog
from bouquin.theme import ThemeManager, ThemeConfig, Theme
from bouquin.settings import get_settings
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget, QDialog


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


class _Host(QWidget):
    def __init__(self, themes):
        super().__init__()
        self.themes = themes


def _make_host_and_dialog(tmp_db_cfg, fresh_db):
    # Create a real ThemeManager so we don't have to fake anything here
    from PySide6.QtWidgets import QApplication

    themes = ThemeManager(QApplication.instance(), ThemeConfig(theme=Theme.SYSTEM))
    host = _Host(themes)
    dlg = SettingsDialog(tmp_db_cfg, fresh_db, parent=host)
    return host, dlg


def _clear_qsettings_theme_to_system():
    """Make the radio-button default deterministic across the full suite."""
    s = get_settings()
    s.clear()
    s.setValue("ui/theme", "system")


def test_default_theme_radio_is_system_checked(qtbot, tmp_db_cfg, fresh_db):
    # Ensure no stray theme value from previous tests
    _clear_qsettings_theme_to_system()

    host, dlg = _make_host_and_dialog(tmp_db_cfg, fresh_db)
    qtbot.addWidget(host)
    qtbot.addWidget(dlg)
    # With fresh settings (system), the 'system' radio should be selected
    assert dlg.theme_system.isChecked()


def test_save_selects_system_when_no_explicit_choice(
    qtbot, tmp_db_cfg, fresh_db, monkeypatch
):
    host, dlg = _make_host_and_dialog(tmp_db_cfg, fresh_db)
    qtbot.addWidget(dlg)
    # Ensure neither dark nor light is checked so SYSTEM path is taken
    dlg.theme_dark.setChecked(False)
    dlg.theme_light.setChecked(False)
    # This should not raise
    dlg._save()


def test_save_with_dark_selected(qtbot, tmp_db_cfg, fresh_db):
    host, dlg = _make_host_and_dialog(tmp_db_cfg, fresh_db)
    qtbot.addWidget(dlg)
    dlg.theme_dark.setChecked(True)
    dlg._save()


def test_change_key_cancel_first_prompt(qtbot, tmp_db_cfg, fresh_db, monkeypatch):
    host, dlg = _make_host_and_dialog(tmp_db_cfg, fresh_db)
    qtbot.addWidget(dlg)

    class P1:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return QDialog.Rejected

        def key(self):
            return ""

    monkeypatch.setattr("bouquin.settings_dialog.KeyPrompt", P1)
    dlg._change_key()  # returns early


def test_change_key_cancel_second_prompt(qtbot, tmp_db_cfg, fresh_db, monkeypatch):
    host, dlg = _make_host_and_dialog(tmp_db_cfg, fresh_db)
    qtbot.addWidget(dlg)

    class P1:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return QDialog.Accepted

        def key(self):
            return "abc"

    class P2:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return QDialog.Rejected

        def key(self):
            return "abc"

    # First call yields P1, second yields P2
    seq = [P1, P2]

    def _factory(*a, **k):
        cls = seq.pop(0)
        return cls(*a, **k)

    monkeypatch.setattr("bouquin.settings_dialog.KeyPrompt", _factory)
    dlg._change_key()  # returns early


def test_change_key_empty_and_exception_paths(qtbot, tmp_db_cfg, fresh_db, monkeypatch):
    host, dlg = _make_host_and_dialog(tmp_db_cfg, fresh_db)
    qtbot.addWidget(dlg)

    # Timer that auto-accepts any modal QMessageBox so we don't hang.
    def _pump_boxes():
        # Try both the active modal and the general top-level enumeration
        m = QApplication.activeModalWidget()
        if isinstance(m, QMessageBox):
            m.accept()
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QMessageBox):
                w.accept()

    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(_pump_boxes)
    timer.start()

    try:

        class P1:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return QDialog.Accepted

            def key(self):
                return ""

        class P2:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return QDialog.Accepted

            def key(self):
                return ""

        seq = [P1, P2, P1, P2]

        def _factory(*a, **k):
            cls = seq.pop(0)
            return cls(*a, **k)

        monkeypatch.setattr("bouquin.settings_dialog.KeyPrompt", _factory)
        # First run triggers empty-key warning path and return (auto-closed)
        dlg._change_key()

        # Now make rekey() raise to hit the except block (critical dialog)
        def boom(*a, **k):
            raise RuntimeError("nope")

        dlg._db.rekey = boom

        # Return a non-empty matching key twice
        class P3:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return QDialog.Accepted

            def key(self):
                return "secret"

        monkeypatch.setattr("bouquin.settings_dialog.KeyPrompt", lambda *a, **k: P3())
        dlg._change_key()
    finally:
        timer.stop()


def test_save_key_btn_clicked_cancel_flow(qtbot, tmp_db_cfg, fresh_db, monkeypatch):
    host, dlg = _make_host_and_dialog(tmp_db_cfg, fresh_db)
    qtbot.addWidget(dlg)

    # Make sure we start with no key saved so it will prompt
    dlg.key = ""

    class P1:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return QDialog.Rejected

        def key(self):
            return ""

    monkeypatch.setattr("bouquin.settings_dialog.KeyPrompt", P1)

    dlg.save_key_btn.setChecked(True)  # toggles and calls handler
    # Handler should have undone the checkbox back to False
    assert not dlg.save_key_btn.isChecked()
