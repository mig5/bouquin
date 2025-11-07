import pytest
from PySide6.QtWidgets import QApplication, QListWidgetItem
from PySide6.QtCore import Qt

from bouquin.db import DBConfig, DBManager
from bouquin.history_dialog import HistoryDialog

@pytest.fixture(scope="module")
def app():
    a = QApplication.instance()
    if a is None:
        a = QApplication([])
    return a

@pytest.fixture
def db(tmp_path):
    cfg = DBConfig(path=tmp_path / "h.db", key="k")
    db = DBManager(cfg)
    assert db.connect()
    # Seed two versions for a date
    db.save_new_version("2025-02-10", "<p>v1</p>", note="v1", set_current=True)
    db.save_new_version("2025-02-10", "<p>v2</p>", note="v2", set_current=True)
    return db

def test_revert_early_returns(app, db, qtbot):
    dlg = HistoryDialog(db, date_iso="2025-02-10")
    qtbot.addWidget(dlg)

    # (1) No current item -> returns immediately
    dlg.list.setCurrentItem(None)
    dlg._revert()  # should not crash and should not accept

    # (2) Selecting the current item -> still returns early
    # Build an item with the *current* id as payload
    cur_id = next(v["id"] for v in db.list_versions("2025-02-10") if v["is_current"])
    it = QListWidgetItem("current")
    it.setData(Qt.UserRole, cur_id)
    dlg.list.addItem(it)
    dlg.list.setCurrentItem(it)
    dlg._revert()  # should return early (no accept called)
