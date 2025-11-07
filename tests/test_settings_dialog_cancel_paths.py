import types
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from bouquin.db import DBConfig, DBManager
from bouquin.settings_dialog import SettingsDialog
from bouquin.settings import APP_NAME, APP_ORG
from bouquin.key_prompt import KeyPrompt
from bouquin.theme import Theme, ThemeManager, ThemeConfig


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance()
    if a is None:
        a = QApplication([])
    a.setApplicationName(APP_NAME)
    a.setOrganizationName(APP_ORG)
    return a


@pytest.fixture
def db(tmp_path):
    cfg = DBConfig(path=tmp_path / "s.db", key="abc")
    m = DBManager(cfg)
    assert m.connect()
    return m


def test_theme_radio_initialisation_dark_and_light(app, db, monkeypatch, qtbot):
    # Dark preselection
    parent = _ParentWithThemes(app)
    qtbot.addWidget(parent)
    dlg = SettingsDialog(db.cfg, db, parent=parent)
    qtbot.addWidget(dlg)
    dlg.theme_dark.setChecked(True)
    dlg._save()
    assert dlg.config.theme == Theme.DARK.value

    # Light preselection
    parent2 = _ParentWithThemes(app)
    qtbot.addWidget(parent2)
    dlg2 = SettingsDialog(db.cfg, db, parent=parent2)
    qtbot.addWidget(dlg2)
    dlg2.theme_light.setChecked(True)
    dlg2._save()
    assert dlg2.config.theme == Theme.LIGHT.value


def test_change_key_cancel_branches(app, db, monkeypatch, qtbot):
    parent = _ParentWithThemes(app)
    qtbot.addWidget(parent)
    dlg = SettingsDialog(db.cfg, db, parent=parent)
    qtbot.addWidget(dlg)

    # First prompt cancelled -> early return
    monkeypatch.setattr(KeyPrompt, "exec", lambda self: QDialog.Rejected)
    dlg._change_key()  # should just return without altering key
    assert dlg.key == ""

    # First OK, second cancelled -> early return at the second branch
    state = {"calls": 0}

    def _exec(self):
        state["calls"] += 1
        return QDialog.Accepted if state["calls"] == 1 else QDialog.Rejected

    monkeypatch.setattr(KeyPrompt, "exec", _exec)
    # Also monkeypatch to control key() values
    monkeypatch.setattr(KeyPrompt, "key", lambda self: "new-secret")
    dlg._change_key()
    # Because the second prompt was rejected, key should remain unchanged
    assert dlg.key == ""


def test_save_key_checkbox_cancel_restores_checkbox(app, db, monkeypatch, qtbot):
    parent = _ParentWithThemes(app)
    qtbot.addWidget(parent)
    dlg = SettingsDialog(db.cfg, db, parent=parent)
    qtbot.addWidget(dlg)
    qtbot.addWidget(dlg)

    # Simulate user checking the box, but cancelling the prompt -> code unchecks it again
    monkeypatch.setattr(KeyPrompt, "exec", lambda self: QDialog.Rejected)
    dlg.save_key_btn.setChecked(True)
    # The slot toggled should run and revert it to unchecked
    assert dlg.save_key_btn.isChecked() is False


def test_change_key_exception_path(app, db, monkeypatch, qtbot):
    parent = _ParentWithThemes(app)
    qtbot.addWidget(parent)
    dlg = SettingsDialog(db.cfg, db, parent=parent)
    qtbot.addWidget(dlg)

    # Accept both prompts and supply a key
    monkeypatch.setattr(KeyPrompt, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(KeyPrompt, "key", lambda self: "boom")

    # Force DB rekey to raise to exercise the except-branch
    monkeypatch.setattr(
        db, "rekey", lambda new_key: (_ for _ in ()).throw(RuntimeError("fail"))
    )

    # Should not raise; error is handled internally
    dlg._change_key()


class _ParentWithThemes(QWidget):
    def __init__(self, app):
        super().__init__()
        self.themes = ThemeManager(app, ThemeConfig())
