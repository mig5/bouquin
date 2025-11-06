from PySide6.QtWidgets import QApplication, QMessageBox
from bouquin.main_window import MainWindow
from bouquin.theme import ThemeManager, ThemeConfig, Theme
from bouquin.db import DBConfig


def _themes_light():
    app = QApplication.instance()
    return ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))


def _themes_dark():
    app = QApplication.instance()
    return ThemeManager(app, ThemeConfig(theme=Theme.DARK))


class FakeDBErr:
    def __init__(self, cfg):
        pass

    def connect(self):
        raise Exception("file is not a database")


class FakeDBOk:
    def __init__(self, cfg):
        pass

    def connect(self):
        return True

    def save_new_version(self, date, text, note):
        raise RuntimeError("nope")

    def get_entry(self, date):
        return "<p>hi</p>"

    def get_entries_days(self):
        return []


def test_try_connect_sqlcipher_error(monkeypatch, qtbot, tmp_path):
    # Config with a key so __init__ calls _try_connect immediately
    cfg = DBConfig(tmp_path / "db.sqlite", key="x")
    (tmp_path / "db.sqlite").write_text("", encoding="utf-8")
    monkeypatch.setattr("bouquin.main_window.load_db_config", lambda: cfg)
    monkeypatch.setattr("bouquin.main_window.DBManager", FakeDBErr)
    msgs = {}
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda p, t, m: msgs.setdefault("m", m))
    )
    w = MainWindow(_themes_light())  # auto-calls _try_connect
    qtbot.addWidget(w)
    assert "incorrect" in msgs.get("m", "").lower()


def test_apply_link_css_dark(qtbot, monkeypatch, tmp_path):
    cfg = DBConfig(tmp_path / "db.sqlite", key="x")
    (tmp_path / "db.sqlite").write_text("", encoding="utf-8")
    monkeypatch.setattr("bouquin.main_window.load_db_config", lambda: cfg)
    monkeypatch.setattr("bouquin.main_window.DBManager", FakeDBOk)
    w = MainWindow(_themes_dark())
    qtbot.addWidget(w)
    w._apply_link_css()
    css = w.editor.document().defaultStyleSheet()
    assert "a {" in css


def test_restore_window_position_first_run(qtbot, monkeypatch, tmp_path):
    cfg = DBConfig(tmp_path / "db.sqlite", key="x")
    (tmp_path / "db.sqlite").write_text("", encoding="utf-8")
    monkeypatch.setattr("bouquin.main_window.load_db_config", lambda: cfg)
    monkeypatch.setattr("bouquin.main_window.DBManager", FakeDBOk)
    w = MainWindow(_themes_light())
    qtbot.addWidget(w)
    called = {}

    class FakeSettings:
        def value(self, key, default=None, type=None):
            if key == "main/geometry":
                return None
            if key == "main/windowState":
                return None
            if key == "main/maximized":
                return False
            return default

    w.settings = FakeSettings()
    monkeypatch.setattr(
        w, "_move_to_cursor_screen_center", lambda: called.setdefault("x", True)
    )
    w._restore_window_position()
    assert called.get("x") is True


def test_on_insert_image_calls_editor(qtbot, monkeypatch, tmp_path):
    cfg = DBConfig(tmp_path / "db.sqlite", key="x")
    (tmp_path / "db.sqlite").write_text("", encoding="utf-8")
    monkeypatch.setattr("bouquin.main_window.load_db_config", lambda: cfg)
    monkeypatch.setattr("bouquin.main_window.DBManager", FakeDBOk)
    w = MainWindow(_themes_light())
    qtbot.addWidget(w)
    captured = {}
    monkeypatch.setattr(
        w.editor, "insert_images", lambda paths: captured.setdefault("p", paths)
    )
    # Simulate file dialog returning paths
    monkeypatch.setattr(
        "bouquin.main_window.QFileDialog.getOpenFileNames",
        staticmethod(lambda *a, **k: (["/tmp/a.png", "/tmp/b.jpg"], "Images")),
    )
    w._on_insert_image()
    assert captured.get("p") == ["/tmp/a.png", "/tmp/b.jpg"]
