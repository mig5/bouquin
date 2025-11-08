from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt

from bouquin.history_dialog import HistoryDialog


def test_history_dialog_lists_and_revert(qtbot, fresh_db):
    d = "2001-01-01"
    fresh_db.save_new_version(d, "v1", "first")
    fresh_db.save_new_version(d, "v2", "second")

    w = QWidget()
    dlg = HistoryDialog(fresh_db, d, parent=w)
    qtbot.addWidget(dlg)
    dlg.show()

    dlg.list.setCurrentRow(1)
    qtbot.mouseClick(dlg.btn_revert, Qt.LeftButton)
    assert fresh_db.get_entry(d) == "v1"
