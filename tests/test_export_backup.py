import csv, json, sqlite3

import pytest

from tests.qt_helpers import trigger_menu_action, accept_all_message_boxes

# Export filters used by the app (format is chosen by this name filter, not by extension)
EXPORT_FILTERS = {
    ".txt": "Text (*.txt)",
    ".json": "JSON (*.json)",
    ".csv": "CSV (*.csv)",
    ".html": "HTML (*.html)",
    ".sql": "SQL (*.sql)",  # app writes a SQLite DB here
}
BACKUP_FILTER = "SQLCipher (*.db)"


def _write_sample_entries(win, qtbot):
    win.editor.setPlainText("alpha <b>bold</b>")
    win._save_current(explicit=True)
    d = win.calendar.selectedDate().addDays(1)
    win.calendar.setSelectedDate(d)
    win.editor.setPlainText("beta text")
    win._save_current(explicit=True)


@pytest.mark.parametrize(
    "ext,verifier",
    [
        (".txt", lambda p: p.read_text(encoding="utf-8").strip()),
        (".json", lambda p: json.loads(p.read_text(encoding="utf-8"))),
        (".csv", lambda p: list(csv.reader(p.open("r", encoding="utf-8-sig")))),
        (".html", lambda p: p.read_text(encoding="utf-8")),
        (".sql", lambda p: p),
    ],
)
def test_export_all_formats(open_window, qtbot, tmp_path, ext, verifier, monkeypatch):
    win = open_window
    _write_sample_entries(win, qtbot)

    out = tmp_path / f"export_test{ext}"

    # 1) Short-circuit the file dialog so it returns our path + the filter we want.
    from PySide6.QtWidgets import QFileDialog

    def fake_getSaveFileName(*args, **kwargs):
        return (str(out), EXPORT_FILTERS[ext])

    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(fake_getSaveFileName)
    )

    # 2) Kick off the export
    trigger_menu_action(win, "Export")

    # 3) Click through the "unencrypted export" warning
    accept_all_message_boxes()

    # 4) Wait for the file to appear (export happens synchronously after the stub)
    qtbot.waitUntil(out.exists, timeout=5000)

    # 5) Dismiss the "Export complete" info box so it can't block later tests
    accept_all_message_boxes()

    # 6) Assert as before
    val = verifier(out)
    if ext == ".json":
        assert isinstance(val, list) and all(
            "date" in d and "content" in d for d in val
        )
    elif ext == ".csv":
        flat = [cell for row in val for cell in row]
        assert any("alpha" in c for c in flat) and any("beta" in c for c in flat)
    elif ext == ".html":
        lower = val.lower()
        assert "<html" in lower and ("<article" in lower or "<body" in lower)
    elif ext == ".txt":
        assert "alpha" in val and "beta" in val
    elif ext == ".sql":
        con = sqlite3.connect(str(out))
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        names = {r[0] for r in cur.fetchall()}
        assert {"pages", "versions"} <= names
        con.close()


def test_backup_encrypted_database(open_window, qtbot, tmp_path, monkeypatch):
    win = open_window
    _write_sample_entries(win, qtbot)

    from PySide6.QtWidgets import QFileDialog

    def fake_getSaveFileName(*args, **kwargs):
        return (str(tmp_path / "backup.db"), BACKUP_FILTER)

    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(fake_getSaveFileName)
    )

    trigger_menu_action(win, "Backup")
    backup = tmp_path / "backup.db"
    qtbot.waitUntil(backup.exists, timeout=5000)

    # The backup path is now ready; proceed as before...
    sqlcipher3 = pytest.importorskip("sqlcipher3")
    con = sqlcipher3.dbapi2.connect(str(backup))
    cur = con.cursor()
    cur.execute("PRAGMA key = 'ci-secret-key';")
    ok = cur.execute("PRAGMA cipher_integrity_check;").fetchall()
    assert ok == []
    con.close()
