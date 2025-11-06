import os
import sys
from pathlib import Path
import pytest
from PySide6.QtCore import QStandardPaths
from tests.qt_helpers import AutoResponder

# Force Qt *non-native* file dialog so we can type a filename programmatically.
os.environ.setdefault("QT_FILE_DIALOG_ALWAYS_USE_NATIVE", "0")
# For CI headless runs, set QT_QPA_PLATFORM=offscreen in the CI env
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Make project importable
from PySide6.QtWidgets import QApplication, QWidget
from bouquin.theme import ThemeManager, ThemeConfig, Theme

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session", autouse=True)
def enable_qstandardpaths_test_mode():
    QStandardPaths.setTestModeEnabled(True)


@pytest.fixture()
def temp_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture()
def clean_settings():
    try:
        from bouquin.settings import APP_NAME, APP_ORG
        from PySide6.QtCore import QSettings
    except Exception:
        yield
        return
    s = QSettings(APP_ORG, APP_NAME)
    s.clear()
    yield
    s.clear()


@pytest.fixture(autouse=True)
def auto_accept_common_dialogs(qtbot):
    ar = AutoResponder()
    ar.start()
    try:
        yield
    finally:
        ar.stop()


@pytest.fixture()
def open_window(qtbot, temp_home, clean_settings):
    """Launch the app and immediately satisfy first-run/unlock key prompts."""
    from bouquin.main_window import MainWindow

    app = QApplication.instance()
    themes = ThemeManager(app, ThemeConfig())
    themes.apply(Theme.SYSTEM)
    win = MainWindow(themes=themes)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    # Immediately satisfy first-run 'Set key' or 'Unlock' prompts if already visible
    AutoResponder().prehandle_key_prompts_if_present()
    return win


@pytest.fixture()
def today_iso():
    from datetime import date

    d = date.today()
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"


@pytest.fixture
def theme_parent_widget(qtbot):
    """A minimal parent that provides .themes.apply(...) like MainWindow."""

    class _ThemesStub:
        def __init__(self):
            self.applied = []

        def apply(self, theme):
            self.applied.append(theme)

    class _Parent(QWidget):
        def __init__(self):
            super().__init__()
            self.themes = _ThemesStub()

    parent = _Parent()
    qtbot.addWidget(parent)
    return parent
