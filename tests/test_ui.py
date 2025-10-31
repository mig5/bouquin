# tests/test_main_window.py
import pytest


@pytest.fixture
def patched_main_window(monkeypatch, qtbot, fake_db_cls, fake_key_prompt_cls):
    """Construct MainWindow with faked DB + KeyPrompt so tests are deterministic."""
    mw_mod = pytest.importorskip("bouquin.main_window")
    # Swap DBManager with in-memory fake
    monkeypatch.setattr(mw_mod, "DBManager", fake_db_cls, raising=True)
    # Make the unlock dialog auto-accept with a known key
    monkeypatch.setattr(mw_mod, "KeyPrompt", fake_key_prompt_cls, raising=True)

    MainWindow = mw_mod.MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    return win, mw_mod, fake_db_cls, fake_key_prompt_cls


def test_always_prompts_for_key_and_uses_it(patched_main_window):
    win, mw_mod, FakeDB, FakeKP = patched_main_window
    # The fake DB instance is on win.db; it records the key provided by the UI flow
    assert isinstance(win.db, FakeDB)
    assert win.db.connected_key == "sekret"
    assert FakeKP.accepted_count >= 1  # was prompted at startup


def test_manual_save_current_day(patched_main_window, qtbot):
    win, *_ = patched_main_window

    # Type into the editor and save
    win.editor.setPlainText("Test note")
    win._save_current(explicit=True)  # call directly to avoid waiting timers

    day = win._current_date_iso()
    assert win.db.get_entry(day) == "Test note"


def test_switch_day_saves_previous(patched_main_window, qtbot):
    from PySide6.QtCore import QDate

    win, *_ = patched_main_window

    # Write on Day 1
    d1 = win.calendar.selectedDate()
    d1_iso = f"{d1.year():04d}-{d1.month():02d}-{d1.day():02d}"
    win.editor.setPlainText("Notes day 1")

    # Trigger a day change (this path calls _on_date_changed via signal)
    d2 = d1.addDays(1)
    win.calendar.setSelectedDate(d2)
    # After changing, previous day should be saved; editor now shows day 2 content (empty)
    assert win.db.get_entry(d1_iso) == "Notes day 1"
    assert win.editor.toPlainText() == ""


def test_calendar_marks_refresh(patched_main_window, qtbot):
    from PySide6.QtCore import QDate
    from PySide6.QtGui import QTextCharFormat, QFont

    win, *_ = patched_main_window

    # Put content on two dates and refresh marks
    today = win.calendar.selectedDate()
    win.db.upsert_entry(f"{today.year():04d}-{today.month():02d}-{today.day():02d}", "x")
    another = today.addDays(2)
    win.db.upsert_entry(f"{another.year():04d}-{another.month():02d}-{another.day():02d}", "y")

    win._refresh_calendar_marks()

    fmt_today = win.calendar.dateTextFormat(today)
    fmt_other = win.calendar.dateTextFormat(another)

    # Both should be bold (DemiBold or Bold depending on platform); we just assert non-Normal
    assert fmt_today.fontWeight() != QFont.Weight.Normal
    assert fmt_other.fontWeight() != QFont.Weight.Normal

