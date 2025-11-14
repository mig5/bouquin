from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QWidget
from bouquin.lock_overlay import LockOverlay
from bouquin.theme import ThemeManager, ThemeConfig, Theme


def test_lock_overlay_reacts_to_theme(app, qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    ol = LockOverlay(host, on_unlock=lambda: None, themes=themes)
    qtbot.addWidget(ol)
    ol.show()

    ev = QEvent(QEvent.Type.PaletteChange)
    ol.changeEvent(ev)
