from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication

from .settings import APP_NAME, APP_ORG, get_settings
from .main_window import MainWindow
from .theme import Theme, ThemeConfig, ThemeManager
from . import strings


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)

    s = get_settings()
    theme_str = s.value("ui/theme", "system")
    cfg = ThemeConfig(theme=Theme(theme_str))
    themes = ThemeManager(app, cfg)
    themes.apply(cfg.theme)

    strings.load_strings(s.value("ui/locale", "en"))
    win = MainWindow(themes=themes)
    win.show()
    sys.exit(app.exec())
