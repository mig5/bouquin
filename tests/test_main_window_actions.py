import os
from datetime import date, timedelta
from pathlib import Path
from PySide6.QtCore import QDate, QByteArray
from bouquin.theme import ThemeManager
from bouquin.main_window import MainWindow
from bouquin.settings import save_db_config
from bouquin.db import DBManager


def _bootstrap_window(qapp, cfg):
    # Ensure DB exists and key is valid in settings
    mgr = DBManager(cfg)
    assert mgr.connect() is True
    save_db_config(cfg)

    themes = ThemeManager(qapp, cfg)
    win = MainWindow(themes)
    # Force an initial selected date
    win.calendar.setSelectedDate(QDate.currentDate())
    return win


def test_move_todos_copies_unchecked(qapp, cfg, tmp_path):
    cfg.move_todos = True
    win = _bootstrap_window(qapp, cfg)

    # Seed yesterday with both checked and unchecked items using the same HTML pattern the app expects
    y = QDate.currentDate().addDays(-1).toString("yyyy-MM-dd")
    html = (
        "<p><span>☐</span> Unchecked 1</p>"
        "<p><span>☑</span> Checked 1</p>"
        "<p><span>☐</span> Unchecked 2</p>"
    )
    win.db.save_new_version(y, html)

    # Ensure today starts blank
    today_iso = QDate.currentDate().toString("yyyy-MM-dd")
    win.editor.setHtml("<p></p>")
    _html = win.editor.toHtml()
    win.db.save_new_version(today_iso, _html)

    # Invoke the move-todos logic
    win._load_yesterday_todos()

    # Verify today's entry now contains only the unchecked items
    txt = win.db.get_entry(today_iso)
    assert "Unchecked 1" in txt and "Unchecked 2" in txt and "Checked 1" not in txt


def test_adjust_and_save_paths(qapp, cfg):
    win = _bootstrap_window(qapp, cfg)

    # Move date selection and jump to today
    before = win.calendar.selectedDate()
    win._adjust_day(-1)
    assert win.calendar.selectedDate().toString("yyyy-MM-dd") != before.toString(
        "yyyy-MM-dd"
    )
    win._adjust_today()
    assert win.calendar.selectedDate() == QDate.currentDate()

    # Save path exercises success feedback + dirty flag reset
    win.editor.setHtml("<p>content</p>")
    win._dirty = True
    win._save_date(QDate.currentDate().toString("yyyy-MM-dd"), explicit=True)
    assert win._dirty is False


def test_restore_window_position(qapp, cfg, tmp_path):
    win = _bootstrap_window(qapp, cfg)

    # Save geometry/state into settings and restore it (covers maximize singleShot branch too)
    geom = win.saveGeometry()
    state = win.saveState()
    s = win.settings
    s.setValue("ui/geometry", geom)
    s.setValue("ui/window_state", state)
    s.sync()

    win._restore_window_position()  # should restore without error


def test_idle_lock_unlock_flow(qapp, cfg):
    win = _bootstrap_window(qapp, cfg)

    # Enter lock
    win._enter_lock()
    assert getattr(win, "_locked", False) is True

    # Disabling idle minutes should unlock and hide overlay
    win._apply_idle_minutes(0)
    assert getattr(win, "_locked", False) is False
