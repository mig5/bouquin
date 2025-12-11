from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import strings
from .main_window import MainWindow
from .settings import APP_NAME, APP_ORG, get_settings
from .theme import Theme, ThemeConfig, ThemeManager


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    # Icon
    BASE_DIR = Path(__file__).resolve().parent
    ICON_PATH = BASE_DIR / "icons" / "bouquin.svg"
    icon = QIcon(str(ICON_PATH))
    app.setWindowIcon(icon)

    s = get_settings()
    theme_str = s.value("ui/theme", "system")
    cfg = ThemeConfig(theme=Theme(theme_str))
    themes = ThemeManager(app, cfg)
    themes.apply(cfg.theme)

    strings.load_strings(s.value("ui/locale", "en"))
    win = MainWindow(themes=themes)
    win.show()
    sys.exit(app.exec())
