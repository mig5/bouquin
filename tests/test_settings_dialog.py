from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QWidget

from bouquin.db import DBConfig
from bouquin.settings_dialog import SettingsDialog
from bouquin.theme import Theme


class _ThemeSpy:
    def __init__(self):
        self.calls = []

    def set(self, t):
        self.calls.append(t)


class _Parent(QWidget):
    def __init__(self):
        super().__init__()
        self.themes = _ThemeSpy()


class FakeDB:
    def __init__(self):
        self.rekey_called_with = None
        self.compact_called = False
        self.fail_compact = False

    def rekey(self, key: str):
        self.rekey_called_with = key

    def compact(self):
        if self.fail_compact:
            raise RuntimeError("boom")
        self.compact_called = True


class AcceptingPrompt:
    def __init__(self, parent=None, title="", message=""):
        self._key = ""
        self._accepted = True

    def set_key(self, k: str):
        self._key = k
        return self

    def exec(self):
        return QDialog.Accepted if self._accepted else QDialog.Rejected

    def key(self):
        return self._key


class RejectingPrompt(AcceptingPrompt):
    def __init__(self, *a, **k):
        super().__init__()
        self._accepted = False


def test_save_persists_all_fields(monkeypatch, qtbot, tmp_path):
    db = FakeDB()
    cfg = DBConfig(path=tmp_path / "db.sqlite", key="", idle_minutes=15)

    saved = {}

    def fake_save(cfg2):
        saved["cfg"] = cfg2

    monkeypatch.setattr("bouquin.settings_dialog.save_db_config", fake_save)

    # Drive the "remember key" checkbox via the prompt (no pre-set key)
    p = AcceptingPrompt().set_key("sekrit")
    monkeypatch.setattr("bouquin.settings_dialog.KeyPrompt", lambda *a, **k: p)

    # Provide a lightweight parent that mimics MainWindow’s `themes` API
    class _ThemeSpy:
        def __init__(self):
            self.calls = []

        def set(self, theme):
            self.calls.append(theme)

    class _Parent(QWidget):
        def __init__(self):
            super().__init__()
            self.themes = _ThemeSpy()

    parent = _Parent()
    qtbot.addWidget(parent)
    dlg = SettingsDialog(cfg, db, parent=parent)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    # Change fields
    new_path = tmp_path / "new.sqlite"
    dlg.path_edit.setText(str(new_path))
    dlg.idle_spin.setValue(0)

    # User toggles "Remember key" -> stores prompted key
    dlg.save_key_btn.setChecked(True)

    dlg._save()

    out = saved["cfg"]
    assert out.path == new_path
    assert out.idle_minutes == 0
    assert out.key == "sekrit"
    assert parent.themes.calls and parent.themes.calls[-1] == Theme.SYSTEM


def test_save_key_checkbox_requires_key_and_reverts_if_cancelled(monkeypatch, qtbot):
    # When toggled on with no key yet, it prompts; cancelling should revert the check
    monkeypatch.setattr("bouquin.settings_dialog.KeyPrompt", RejectingPrompt)

    dlg = SettingsDialog(DBConfig(Path("x"), key=""), FakeDB())
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    assert dlg.key == ""
    dlg.save_key_btn.click()  # toggles True -> triggers prompt which rejects
    assert dlg.save_key_btn.isChecked() is False
    assert dlg.key == ""


def test_save_key_checkbox_accepts_and_stores_key(monkeypatch, qtbot):
    # Toggling on with an accepting prompt should store the typed key
    p = AcceptingPrompt().set_key("remember-me")
    monkeypatch.setattr("bouquin.settings_dialog.KeyPrompt", lambda *a, **k: p)

    dlg = SettingsDialog(DBConfig(Path("x"), key=""), FakeDB())
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    dlg.save_key_btn.click()
    assert dlg.save_key_btn.isChecked() is True
    assert dlg.key == "remember-me"


def test_change_key_success(monkeypatch, qtbot):
    # Two prompts returning the same non-empty key -> rekey() and info message
    p1 = AcceptingPrompt().set_key("newkey")
    p2 = AcceptingPrompt().set_key("newkey")
    seq = [p1, p2]
    monkeypatch.setattr("bouquin.settings_dialog.KeyPrompt", lambda *a, **k: seq.pop(0))

    shown = {"info": 0}
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *a, **k: shown.__setitem__("info", shown["info"] + 1),
    )

    db = FakeDB()
    dlg = SettingsDialog(DBConfig(Path("x"), key=""), db)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    dlg._change_key()

    assert db.rekey_called_with == "newkey"
    assert shown["info"] >= 1
    assert dlg.key == "newkey"


def test_change_key_mismatch_shows_warning_and_no_rekey(monkeypatch, qtbot):
    p1 = AcceptingPrompt().set_key("a")
    p2 = AcceptingPrompt().set_key("b")
    seq = [p1, p2]
    monkeypatch.setattr("bouquin.settings_dialog.KeyPrompt", lambda *a, **k: seq.pop(0))

    called = {"warn": 0}
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *a, **k: called.__setitem__("warn", called["warn"] + 1),
    )

    db = FakeDB()
    dlg = SettingsDialog(DBConfig(Path("x"), key=""), db)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    dlg._change_key()

    assert db.rekey_called_with is None
    assert called["warn"] >= 1


def test_change_key_empty_shows_warning(monkeypatch, qtbot):
    p1 = AcceptingPrompt().set_key("")
    p2 = AcceptingPrompt().set_key("")
    seq = [p1, p2]
    monkeypatch.setattr("bouquin.settings_dialog.KeyPrompt", lambda *a, **k: seq.pop(0))

    called = {"warn": 0}
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *a, **k: called.__setitem__("warn", called["warn"] + 1),
    )

    db = FakeDB()
    dlg = SettingsDialog(DBConfig(Path("x"), key=""), db)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    dlg._change_key()

    assert db.rekey_called_with is None
    assert called["warn"] >= 1


def test_browse_sets_path(monkeypatch, qtbot, tmp_path):
    def fake_get_save_file_name(*a, **k):
        return (str(tmp_path / "picked.sqlite"), "")

    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(fake_get_save_file_name)
    )

    dlg = SettingsDialog(DBConfig(Path("x"), key=""), FakeDB())
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    dlg._browse()
    assert dlg.path_edit.text().endswith("picked.sqlite")


def test_compact_success_and_failure(monkeypatch, qtbot):
    shown = {"info": 0, "crit": 0}
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *a, **k: shown.__setitem__("info", shown["info"] + 1),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda *a, **k: shown.__setitem__("crit", shown["crit"] + 1),
    )

    db = FakeDB()
    dlg = SettingsDialog(DBConfig(Path("x"), key=""), db)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    dlg._compact_btn_clicked()
    assert db.compact_called is True
    assert shown["info"] >= 1

    # Failure path
    db2 = FakeDB()
    db2.fail_compact = True
    dlg2 = SettingsDialog(DBConfig(Path("x"), key=""), db2)
    qtbot.addWidget(dlg2)
    dlg2.show()
    qtbot.waitExposed(dlg2)

    dlg2._compact_btn_clicked()
    assert shown["crit"] >= 1


def test_save_key_checkbox_preexisting_key_does_not_crash(monkeypatch, qtbot):
    p = AcceptingPrompt().set_key("already")
    monkeypatch.setattr("bouquin.settings_dialog.KeyPrompt", lambda *a, **k: p)

    dlg = SettingsDialog(DBConfig(Path("x"), key="already"), FakeDB())
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    dlg.save_key_btn.setChecked(True)
    # We should reach here with the original key preserved.
    assert dlg.key == "already"


def test_save_unchecked_clears_key_and_applies_theme(qtbot, tmp_path):
    parent = _Parent()
    qtbot.addWidget(parent)
    cfg = DBConfig(tmp_path / "db.sqlite", key="sekrit", idle_minutes=5)
    dlg = SettingsDialog(cfg, FakeDB(), parent=parent)
    qtbot.addWidget(dlg)
    dlg.save_key_btn.setChecked(False)
    # Trigger save
    dlg._save()
    assert dlg.config.key == ""  # cleared
    assert parent.themes.calls  # applied some theme
