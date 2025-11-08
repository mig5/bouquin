import pytest
from PySide6.QtGui import QPalette

from bouquin.theme import Theme, ThemeConfig, ThemeManager


def test_theme_manager_apply_light_and_dark(app):
    cfg = ThemeConfig(theme=Theme.LIGHT)
    mgr = ThemeManager(app, cfg)
    mgr.apply(Theme.LIGHT)
    assert isinstance(app.palette(), QPalette)

    mgr.set(Theme.DARK)
    assert isinstance(app.palette(), QPalette)


@pytest.mark.gui
def test_theme_manager_system_roundtrip(app, qtbot):
    cfg = ThemeConfig(theme=Theme.SYSTEM)
    mgr = ThemeManager(app, cfg)
    mgr.apply(cfg.theme)
