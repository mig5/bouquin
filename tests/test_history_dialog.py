from PySide6.QtWidgets import QWidget, QMessageBox, QApplication
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


def test_revert_returns_when_no_item_selected(qtbot, fresh_db):
    d = "2000-01-01"
    fresh_db.save_new_version(d, "v1", "first")
    w = QWidget()
    dlg = HistoryDialog(fresh_db, d, parent=w)
    qtbot.addWidget(dlg)
    dlg.show()
    # No selection at all -> early return
    dlg.list.clearSelection()
    dlg._revert()  # should not raise


def test_revert_returns_when_current_selected(qtbot, fresh_db):
    d = "2000-01-02"
    fresh_db.save_new_version(d, "v1", "first")
    # Create a second version so there is a 'current'
    fresh_db.save_new_version(d, "v2", "second")
    w = QWidget()
    dlg = HistoryDialog(fresh_db, d, parent=w)
    qtbot.addWidget(dlg)
    dlg.show()
    # Select the current item -> early return
    for i in range(dlg.list.count()):
        item = dlg.list.item(i)
        if item.data(Qt.UserRole) == dlg._current_id:
            dlg.list.setCurrentItem(item)
            break
    dlg._revert()  # no-op


def test_revert_exception_shows_message(qtbot, fresh_db, monkeypatch):
    """
    Trigger the exception path in _revert() and auto-accept the modal
    QMessageBox that HistoryDialog pops so the test doesn't hang.
    """
    d = "2000-01-03"
    fresh_db.save_new_version(d, "v1", "first")
    fresh_db.save_new_version(d, "v2", "second")

    w = QWidget()
    dlg = HistoryDialog(fresh_db, d, parent=w)
    qtbot.addWidget(dlg)
    dlg.show()

    # Select a non-current item
    for i in range(dlg.list.count()):
        item = dlg.list.item(i)
        if item.data(Qt.UserRole) != dlg._current_id:
            dlg.list.setCurrentItem(item)
            break

    # Make revert raise to hit the except/critical message path.
    def boom(*_a, **_k):
        raise RuntimeError("nope")

    monkeypatch.setattr(dlg._db, "revert_to_version", boom)

    # Prepare a small helper that keeps trying to close an active modal box,
    # but gives up after a bounded number of attempts.
    def make_closer(max_tries=50, interval_ms=10):
        tries = {"n": 0}

        def closer():
            tries["n"] += 1
            w = QApplication.activeModalWidget()
            if isinstance(w, QMessageBox):
                # Prefer clicking the OK button if present; otherwise accept().
                ok = w.button(QMessageBox.Ok)
                if ok is not None:
                    ok.click()
                else:
                    w.accept()
            elif tries["n"] < max_tries:
                QTimer.singleShot(interval_ms, closer)

        return closer

    # Schedule auto-close right before we trigger the modal dialog.
    QTimer.singleShot(0, make_closer())

    # Should show the critical box, which our timer will accept; _revert returns.
    dlg._revert()


def test_delete_version_from_history(qtbot, fresh_db):
    """Test deleting a version through the history dialog."""
    d = "2001-01-01"

    # Create multiple versions
    vid1, _ = fresh_db.save_new_version(d, "v1", "first")
    vid2, _ = fresh_db.save_new_version(d, "v2", "second")
    vid3, _ = fresh_db.save_new_version(d, "v3", "third")

    w = QWidget()
    dlg = HistoryDialog(fresh_db, d, parent=w)
    qtbot.addWidget(dlg)
    dlg.show()

    # Verify we have 3 versions
    assert dlg.list.count() == 3

    # Select the first version (oldest, not current)
    dlg.list.setCurrentRow(2)  # Last row is oldest version

    # Call _delete
    dlg._delete()

    # Verify the version was deleted
    assert dlg.list.count() == 2

    # Verify from DB
    versions = fresh_db.list_versions(d)
    assert len(versions) == 2


def test_delete_current_version_returns_early(qtbot, fresh_db):
    """Test that deleting the current version returns early without deleting."""
    d = "2001-01-02"

    # Create versions
    vid1, _ = fresh_db.save_new_version(d, "v1", "first")
    vid2, _ = fresh_db.save_new_version(d, "v2", "second")

    w = QWidget()
    dlg = HistoryDialog(fresh_db, d, parent=w)
    qtbot.addWidget(dlg)
    dlg.show()

    # Find and select the current version
    for i in range(dlg.list.count()):
        item = dlg.list.item(i)
        if item.data(Qt.UserRole) == dlg._current_id:
            dlg.list.setCurrentItem(item)
            break

    # Try to delete - should return early
    dlg._delete()

    # Verify nothing was deleted
    versions = fresh_db.list_versions(d)
    assert len(versions) == 2


def test_delete_version_with_error(qtbot, fresh_db, monkeypatch):
    """Test that delete version error shows a message box."""
    d = "2001-01-03"

    # Create versions
    vid1, _ = fresh_db.save_new_version(d, "v1", "first")
    vid2, _ = fresh_db.save_new_version(d, "v2", "second")

    w = QWidget()
    dlg = HistoryDialog(fresh_db, d, parent=w)
    qtbot.addWidget(dlg)
    dlg.show()

    # Select a non-current version
    for i in range(dlg.list.count()):
        item = dlg.list.item(i)
        if item.data(Qt.UserRole) != dlg._current_id:
            dlg.list.setCurrentItem(item)
            break

    # Make delete_version raise an error
    def boom(*args, **kwargs):
        raise RuntimeError("Delete failed")

    monkeypatch.setattr(dlg._db, "delete_version", boom)

    # Set up auto-closer for message box
    def make_closer(max_tries=50, interval_ms=10):
        tries = {"n": 0}

        def closer():
            tries["n"] += 1
            w = QApplication.activeModalWidget()
            if isinstance(w, QMessageBox):
                ok = w.button(QMessageBox.Ok)
                if ok is not None:
                    ok.click()
                else:
                    w.accept()
            elif tries["n"] < max_tries:
                QTimer.singleShot(interval_ms, closer)

        return closer

    QTimer.singleShot(0, make_closer())

    # Call delete - should show error message
    dlg._delete()


def test_delete_multiple_versions(qtbot, fresh_db):
    """Test deleting multiple versions at once."""
    d = "2001-01-04"

    # Create multiple versions
    vid1, _ = fresh_db.save_new_version(d, "v1", "first")
    vid2, _ = fresh_db.save_new_version(d, "v2", "second")
    vid3, _ = fresh_db.save_new_version(d, "v3", "third")
    vid4, _ = fresh_db.save_new_version(d, "v4", "fourth")

    w = QWidget()
    dlg = HistoryDialog(fresh_db, d, parent=w)
    qtbot.addWidget(dlg)
    dlg.show()

    # Select multiple non-current items
    selected_count = 0
    for i in range(dlg.list.count()):
        item = dlg.list.item(i)
        if item.data(Qt.UserRole) != dlg._current_id:
            item.setSelected(True)
            selected_count += 1
            if selected_count >= 2:  # Select 2 items
                break

    # Delete them
    dlg._delete()

    # Verify versions were deleted (should have current + 1 remaining)
    versions = fresh_db.list_versions(d)
    assert len(versions) == 2  # Current + 1 that wasn't deleted
