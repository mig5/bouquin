import importlib
import runpy

import pytest


def test_main_module_has_main():
    m = importlib.import_module("bouquin.main")
    assert hasattr(m, "main")


def test_dunder_main_imports_main():
    m = importlib.import_module("bouquin.__main__")
    assert hasattr(m, "main")


def test_dunder_main_calls_main(monkeypatch):
    called = {"ok": False}

    def fake_main():
        called["ok"] = True

    # Replace real main with a stub to avoid launching Qt event loop
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # Ensure that when __main__ imports from .main it gets our stub
    import bouquin.main as real_main

    monkeypatch.setattr(real_main, "main", fake_main, raising=True)
    # Execute the module as a script
    runpy.run_module("bouquin.__main__", run_name="__main__")
    assert called["ok"]


def test_main_creates_and_shows(monkeypatch):
    # Create a fake QApplication with the minimal API
    class FakeApp:
        def __init__(self, argv):
            self.ok = True

        def setApplicationName(self, *_):
            pass

        def setOrganizationName(self, *_):
            pass

        def setWindowIcon(self, *_):
            pass

        def exec(self):
            return 0

    class FakeWin:
        def __init__(self, themes=None):
            self.shown = False

        def show(self):
            self.shown = True

    class FakeSettings:
        def value(self, k, default=None):
            return "light" if k == "ui/theme" else default

    # Patch imports inside bouquin.main
    import bouquin.main as m

    monkeypatch.setattr(m, "QApplication", FakeApp, raising=True)
    monkeypatch.setattr(m, "MainWindow", FakeWin, raising=True)

    # Theme classes
    class FakeTM:
        def __init__(self, app, cfg):
            pass

        def apply(self, theme):
            pass

    class FakeTheme:
        def __init__(self, s):
            pass

    class FakeCfg:
        def __init__(self, theme):
            self.theme = theme

    monkeypatch.setattr(m, "ThemeManager", FakeTM, raising=True)
    monkeypatch.setattr(m, "Theme", FakeTheme, raising=True)
    monkeypatch.setattr(m, "ThemeConfig", FakeCfg, raising=True)

    # get_settings() used inside main()
    def fake_get_settings():
        return FakeSettings()

    monkeypatch.setattr(m, "get_settings", fake_get_settings, raising=True)

    # Run
    with pytest.raises(SystemExit) as e:
        m.main()
    assert e.value.code == 0
