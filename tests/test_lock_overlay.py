import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QWidget
from bouquin.lock_overlay import LockOverlay


@pytest.mark.gui
def test_lock_overlay_reacts_to_theme(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.show()

    ol = LockOverlay(host, on_unlock=lambda: None)
    qtbot.addWidget(ol)
    ol.show()

    ev = QEvent(QEvent.Type.PaletteChange)
    ol.changeEvent(ev)
