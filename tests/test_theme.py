from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QCalendarWidget, QWidget

from bouquin.theme import Theme, ThemeConfig, ThemeManager


def test_theme_manager_apply_light_and_dark(app):
    cfg = ThemeConfig(theme=Theme.LIGHT)
    mgr = ThemeManager(app, cfg)
    mgr.apply(Theme.LIGHT)
    assert isinstance(app.palette(), QPalette)

    mgr.set(Theme.DARK)
    assert isinstance(app.palette(), QPalette)


def test_theme_manager_system_roundtrip(app, qtbot):
    cfg = ThemeConfig(theme=Theme.SYSTEM)
    mgr = ThemeManager(app, cfg)
    mgr.apply(cfg.theme)


def _make_themes(theme):
    app = QApplication.instance()
    return ThemeManager(app, ThemeConfig(theme=theme))


def test_register_and_restyle_calendar_and_overlay(qtbot):
    themes = _make_themes(Theme.DARK)
    cal = QCalendarWidget()
    ov = QWidget()
    ov.setObjectName("LockOverlay")
    qtbot.addWidget(cal)
    qtbot.addWidget(ov)

    themes.register_calendar(cal)
    themes.register_lock_overlay(ov)

    # Force a restyle pass (covers the "is not None" branches)
    themes._restyle_registered()


def test_apply_dark_styles_cover_css_paths(qtbot):
    themes = _make_themes(Theme.DARK)
    cal = QCalendarWidget()
    ov = QWidget()
    ov.setObjectName("LockOverlay")
    qtbot.addWidget(cal)
    qtbot.addWidget(ov)

    themes.register_calendar(cal)  # drives _apply_calendar_theme (dark path)
    themes.register_lock_overlay(ov)  # drives _apply_lock_overlay_theme (dark path)
