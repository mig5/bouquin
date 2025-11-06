from PySide6.QtWidgets import QListWidgetItem
from PySide6.QtCore import Qt
from bouquin.history_dialog import HistoryDialog


class FakeDB:
    def __init__(self):
        self.fail_revert = False

    def list_versions(self, date_iso):
        # Simulate two versions; mark second as current
        return [
            {
                "id": 1,
                "version_no": 1,
                "created_at": "2025-01-01T10:00:00Z",
                "note": None,
                "is_current": False,
                "content": "<p>a</p>",
            },
            {
                "id": 2,
                "version_no": 2,
                "created_at": "2025-01-02T10:00:00Z",
                "note": None,
                "is_current": True,
                "content": "<p>b</p>",
            },
        ]

    def get_version(self, version_id):
        if version_id == 2:
            return {"content": "<p>b</p>"}
        return {"content": "<p>a</p>"}

    def revert_to_version(self, date, version_id=None, version_no=None):
        if self.fail_revert:
            raise RuntimeError("boom")


def test_on_select_no_item(qtbot):
    dlg = HistoryDialog(FakeDB(), "2025-01-01")
    qtbot.addWidget(dlg)
    dlg.list.clear()
    dlg._on_select()


def test_revert_failure_shows_critical(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    fake = FakeDB()
    fake.fail_revert = True
    dlg = HistoryDialog(fake, "2025-01-01")
    qtbot.addWidget(dlg)
    item = QListWidgetItem("v1")
    item.setData(Qt.UserRole, 1)  # different from current 2
    dlg.list.addItem(item)
    dlg.list.setCurrentItem(item)
    msgs = {}

    def fake_crit(parent, title, text):
        msgs["t"] = (title, text)

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(fake_crit))
    dlg._revert()
    assert "Revert failed" in msgs["t"][0]
