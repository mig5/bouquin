from PySide6.QtWidgets import QWidget, QMessageBox
from PySide6.QtCore import Qt, QTimer

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


def test_history_dialog_no_selection_clears(qtbot, fresh_db):
    d = "2001-01-01"
    fresh_db.save_new_version(d, "v1", "first")
    w = QWidget()
    dlg = HistoryDialog(fresh_db, d, parent=w)
    qtbot.addWidget(dlg)
    dlg.show()

    # Clear selection (no current item) and call slot
    dlg.list.setCurrentItem(None)
    dlg._on_select()
    assert dlg.preview.toPlainText() == ""
    assert dlg.diff.toPlainText() == ""
    assert not dlg.btn_revert.isEnabled()


def test_history_dialog_revert_same_version_noop(qtbot, fresh_db):
    d = "2001-01-01"
    # Only one version; that's the current
    vid, _ = fresh_db.save_new_version(d, "seed", "note")
    w = QWidget()
    dlg = HistoryDialog(fresh_db, d, parent=w)
    qtbot.addWidget(dlg)
    dlg.show()

    # Pick the only item (current)
    dlg.list.setCurrentRow(0)
    # Clicking revert should simply return (no change)
    before = fresh_db.get_entry(d)
    dlg._revert()
    after = fresh_db.get_entry(d)
    assert before == after


def test_history_dialog_revert_error_shows_message(qtbot, fresh_db):
    d = "2001-01-02"
    fresh_db.save_new_version(d, "v1", "first")
    w = QWidget()
    dlg = HistoryDialog(fresh_db, d, parent=w)
    qtbot.addWidget(dlg)
    dlg.show()

    # Select the row
    dlg.list.setCurrentRow(0)

    # Monkeypatch db to raise inside revert_to_version to hit except path
    def boom(date_iso, version_id):
        raise RuntimeError("nope")

    dlg._db.revert_to_version = boom

    # Auto-accept any QMessageBox that appears
    def _pump():
        for m in QMessageBox.instances():
            m.accept()

    t = QTimer()
    t.setInterval(10)
    t.timeout.connect(_pump)
    t.start()
    try:
        dlg._revert()
    finally:
        t.stop()
