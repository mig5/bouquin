import importlib


def test___main___exports_main():
    entry_mod = importlib.import_module("bouquin.__main__")
    main_mod = importlib.import_module("bouquin.main")
    assert entry_mod.main is main_mod.main


def test_main_entry_initializes_qt(monkeypatch):
    main_mod = importlib.import_module("bouquin.main")

    # Fakes to avoid real Qt event loop
    class FakeApp:
        def __init__(self, argv):
            self.argv = argv
            self.name = None
            self.org = None

        def setApplicationName(self, n):
            self.name = n

        def setOrganizationName(self, n):
            self.org = n

        def exec(self):
            return 0

    class FakeWin:
        def __init__(self, themes=None):
            self.themes = themes
            self.shown = False

        def show(self):
            self.shown = True

    class FakeThemes:
        def __init__(self, app, cfg):
            self._applied = None
            self.app = app
            self.cfg = cfg

        def apply(self, t):
            self._applied = t

    class FakeSettings:
        def __init__(self):
            self._map = {"ui/theme": "dark"}

        def value(self, k, default=None, type=None):
            return self._map.get(k, default)

    def fake_get_settings():
        return FakeSettings()

    monkeypatch.setattr(main_mod, "QApplication", FakeApp)
    monkeypatch.setattr(main_mod, "MainWindow", FakeWin)
    monkeypatch.setattr(main_mod, "ThemeManager", FakeThemes)
    monkeypatch.setattr(main_mod, "get_settings", fake_get_settings)

    exits = {}

    def fake_exit(code):
        exits["code"] = code

    monkeypatch.setattr(main_mod.sys, "exit", fake_exit)

    main_mod.main()
    assert exits.get("code", None) == 0
