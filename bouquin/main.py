from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication

from .settings import APP_NAME, APP_ORG
from .main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
