from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor

from bouquin.theme import ThemeManager, ThemeConfig, Theme


def test_theme_manager_applies_palettes(qtbot):
    app = QApplication.instance()
    tm = ThemeManager(app, ThemeConfig())

    # Light palette should set Link to the light blue
    tm.apply(Theme.LIGHT)
    pal = app.palette()
    assert pal.color(QPalette.Link) == QColor("#1a73e8")

    # Dark palette should set Link to lavender-ish
    tm.apply(Theme.DARK)
    pal = app.palette()
    assert pal.color(QPalette.Link) == QColor("#FFA500")
