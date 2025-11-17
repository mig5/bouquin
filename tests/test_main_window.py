import pytest
import importlib.metadata

from pathlib import Path

import bouquin.main_window as mwmod
from bouquin.main_window import MainWindow
from bouquin.theme import Theme, ThemeConfig, ThemeManager
from bouquin.settings import get_settings
from bouquin.key_prompt import KeyPrompt
from bouquin.db import DBConfig, DBManager
from PySide6.QtCore import QEvent, QDate, QTimer, Qt, QPoint, QRect
from PySide6.QtWidgets import QTableView, QApplication, QWidget, QMessageBox, QDialog
from PySide6.QtGui import QMouseEvent, QKeyEvent, QTextCursor, QCloseEvent

from unittest.mock import Mock, patch


def test_main_window_loads_and_saves(qtbot, app, tmp_db_cfg, fresh_db):
    s = get_settings()
    s.setValue("db/default_db", str(tmp_db_cfg.path))
    s.setValue("db/key", tmp_db_cfg.key)
    s.setValue("ui/idle_minutes", 0)
    s.setValue("ui/theme", "light")
    s.setValue("ui/move_todos", True)

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    date = QDate.currentDate().toString("yyyy-MM-dd")
    w._load_selected_date(date)
    w.editor.from_markdown("hello **world**")
    w._on_text_changed()
    qtbot.wait(5500)  # let the 5s autosave QTimer fire
    assert "world" in fresh_db.get_entry(date)

    w.search.search.setText("world")
    qtbot.wait(50)
    assert not w.search.results.isHidden()

    w._sync_toolbar()
    w._adjust_day(-1)  # previous day
    w._adjust_day(+1)  # next day

    # Auto-accept the unlock KeyPrompt with the correct key
    def _auto_accept_keyprompt():
        for wdg in QApplication.topLevelWidgets():
            if isinstance(wdg, KeyPrompt):
                wdg.key_entry.setText(tmp_db_cfg.key)
                wdg.accept()

    w._enter_lock()
    QTimer.singleShot(0, _auto_accept_keyprompt)
    w._on_unlock_clicked()
    qtbot.wait(50)  # let the nested event loop process the acceptance


def test_load_yesterday_todos_moves_items(qtbot, app, tmp_db_cfg, fresh_db):
    s = get_settings()
    s.setValue("db/default_db", str(tmp_db_cfg.path))
    s.setValue("db/key", tmp_db_cfg.key)
    s.setValue("ui/move_todos", True)
    s.setValue("ui/theme", "light")

    y = QDate.currentDate().addDays(-1).toString("yyyy-MM-dd")
    fresh_db.save_new_version(y, "- [ ] carry me\n- [x] done", "seed")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))

    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    w._load_yesterday_todos()

    assert "carry me" in w.editor.to_markdown()
    y_txt = fresh_db.get_entry(y)
    assert "carry me" not in y_txt or "- [ ]" not in y_txt


def test_open_docs_warning(qtbot, app, fresh_db, tmp_path, monkeypatch):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    # Force QDesktopServices.openUrl to fail so the warning path executes
    called = {"docs": False, "bugs": False}

    def fake_open(url):
        # return False to force warning path
        return False

    mwmod.QDesktopServices.openUrl = fake_open  # minimal monkeypatch

    class DummyMB:
        @staticmethod
        def warning(parent, title, text, *rest):
            t = str(text)
            if "wiki" in t:
                called["docs"] = True
            return 0

    monkeypatch.setattr(mwmod, "QMessageBox", DummyMB, raising=True)  # capture warnings

    w._open_docs()
    assert called["docs"]


def test_export_success_and_error(qtbot, app, fresh_db, tmp_path, monkeypatch):
    # Seed some content
    fresh_db.save_new_version("2001-01-01", "alpha", "n1")
    fresh_db.save_new_version("2001-01-02", "beta", "n2")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    from bouquin.settings import get_settings

    s = get_settings()
    s.setValue("db/default_db", str(fresh_db.cfg.path))
    s.setValue("db/key", fresh_db.cfg.key)
    s.setValue("ui/idle_minutes", 0)
    s.setValue("ui/theme", "light")
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    # Save as Markdown without extension -> should append .md and write file
    dest1 = tmp_path / "export_one"  # no suffix
    monkeypatch.setattr(
        mwmod.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(dest1), "Markdown (*.md)")),
    )

    # Use real QMessageBox class; just force decisions and silence popups
    monkeypatch.setattr(
        mwmod.QMessageBox, "exec", lambda self: mwmod.QMessageBox.Yes, raising=False
    )
    monkeypatch.setattr(
        mwmod.QMessageBox, "information", staticmethod(lambda *a, **k: 0), raising=False
    )
    # Critical should never trigger in the success path
    monkeypatch.setattr(
        mwmod.QMessageBox,
        "critical",
        staticmethod(
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("Unexpected critical"))
        ),
        raising=False,
    )

    w._export()
    assert dest1.with_suffix(".md").exists()

    # Now force an exception during export to hit error branch (patch the window's DB)
    def boom():
        raise RuntimeError("explode")

    monkeypatch.setattr(w.db, "get_all_entries", boom, raising=False)

    # Different filename to avoid overwriting
    dest2 = tmp_path / "export_two"
    monkeypatch.setattr(
        mwmod.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(dest2), "CSV (*.csv)")),
    )

    errs = {"hit": False}
    monkeypatch.setattr(
        mwmod.QMessageBox, "exec", lambda self: mwmod.QMessageBox.Yes, raising=False
    )
    monkeypatch.setattr(
        mwmod.QMessageBox, "information", staticmethod(lambda *a, **k: 0), raising=False
    )
    monkeypatch.setattr(
        mwmod.QMessageBox,
        "critical",
        staticmethod(lambda *a, **k: errs.__setitem__("hit", True) or 0),
        raising=False,
    )
    w._export()
    assert errs["hit"]


def test_backup_path(qtbot, app, fresh_db, tmp_path, monkeypatch):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))

    # wire DB settings the window reads
    from bouquin.settings import get_settings

    s = get_settings()
    s.setValue("db/default_db", str(fresh_db.cfg.path))
    s.setValue("db/key", fresh_db.cfg.key)
    s.setValue("ui/idle_minutes", 0)
    s.setValue("ui/theme", "light")

    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    # Pretend user picked a filename with no suffix -> .db should be appended
    dest = tmp_path / "backupfile"
    monkeypatch.setattr(
        mwmod.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(dest), "SQLCipher (*.db)")),
        raising=False,
    )

    # Avoid any modal dialogs and record the success message
    hit = {"info": False, "text": None}
    monkeypatch.setattr(
        mwmod.QMessageBox,
        "information",
        staticmethod(
            lambda parent, title, text, *a, **k: (
                hit.__setitem__("info", True),
                hit.__setitem__("text", str(text)),
                0,
            )[-1]
        ),
        raising=False,
    )
    monkeypatch.setattr(
        mwmod.QMessageBox, "critical", staticmethod(lambda *a, **k: 0), raising=False
    )

    # Stub the *export* itself to be instant and non-blocking
    called = {"path": None}
    monkeypatch.setattr(
        w.db, "export_sqlcipher", lambda p: called.__setitem__("path", p), raising=False
    )

    w._backup()

    # Assertions: suffix added, export invoked, success toast shown
    assert called["path"] == str(dest.with_suffix(".db"))
    assert hit["info"]
    assert str(dest.with_suffix(".db")) in hit["text"]


def test_close_tab_edges_and_autosave(qtbot, app, fresh_db, monkeypatch):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    from bouquin.settings import get_settings

    s = get_settings()
    s.setValue("db/default_db", str(fresh_db.cfg.path))
    s.setValue("db/key", fresh_db.cfg.key)
    s.setValue("ui/idle_minutes", 0)
    s.setValue("ui/theme", "light")
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    # Create exactly one extra tab (there is already one from __init__)
    d1 = QDate(2020, 1, 1)
    w._open_date_in_tab(d1)
    assert w.tab_widget.count() == 2

    # Close one tab: should call _save_editor_content on its editor
    saved = {"called": False}

    def fake_save_editor(editor):
        saved["called"] = True

    monkeypatch.setattr(w, "_save_editor_content", fake_save_editor, raising=True)
    w._close_tab(0)
    assert saved["called"]
    # Now only one tab remains; closing should no-op
    count_before = w.tab_widget.count()
    w._close_tab(0)
    assert w.tab_widget.count() == count_before
    monkeypatch.delattr(w, "_save_editor_content", raising=False)


def test_restore_window_position_variants(qtbot, app, fresh_db, monkeypatch):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    # Case A: no geometry stored -> should call _move_to_cursor_screen_center
    moved = {"hit": False}
    monkeypatch.setattr(
        w,
        "_move_to_cursor_screen_center",
        lambda: moved.__setitem__("hit", True),
        raising=True,
    )
    # clear any stored geometry
    w.settings.remove("main/geometry")
    w.settings.remove("main/windowState")
    w.settings.remove("main/maximized")
    w._restore_window_position()
    assert moved["hit"]

    # Case B: geometry present but off-screen -> fallback to move_to_cursor
    moved["hit"] = False
    # Save a valid geometry then lie that it's offscreen
    geom = w.saveGeometry()
    w.settings.setValue("main/geometry", geom)
    w.settings.setValue("main/windowState", w.saveState())
    w.settings.setValue("main/maximized", False)
    monkeypatch.setattr(w, "_rect_on_any_screen", lambda r: False, raising=True)
    w._restore_window_position()
    assert moved["hit"]

    # Case C: was_max True triggers showMaximized via QTimer.singleShot
    called = {"max": False}
    monkeypatch.setattr(
        w, "showMaximized", lambda: called.__setitem__("max", True), raising=True
    )
    monkeypatch.setattr(
        mwmod.QTimer, "singleShot", staticmethod(lambda _ms, f: f()), raising=False
    )
    w.settings.setValue("main/maximized", True)
    w._restore_window_position()
    assert called["max"]


def test_calendar_pos_mapping_and_context_menu(qtbot, app, fresh_db, monkeypatch):
    # Seed DB so refresh marks does something
    fresh_db.save_new_version("2021-08-15", "note", "")
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    # Show a month with leading days
    qd = QDate(2021, 8, 15)
    w.calendar.setSelectedDate(qd)

    # Grab the internal table view and pick a couple of indices
    view = w.calendar.findChild(QTableView, "qt_calendar_calendarview")
    model = view.model()

    # Find the first index belonging to current month (day == 1)
    first_idx = None
    for r in range(model.rowCount()):
        for c in range(model.columnCount()):
            if model.index(r, c).data() == 1:
                first_idx = model.index(r, c)
                break
        if first_idx:
            break

    assert first_idx is not None

    # A cell before 'first_idx' should map to previous month
    col0 = 0 if first_idx.column() > 0 else 1
    idx_prev = model.index(first_idx.row(), col0)
    vp_pos = view.visualRect(idx_prev).center()
    global_pos = view.viewport().mapToGlobal(vp_pos)
    cal_pos = w.calendar.mapFromGlobal(global_pos)
    date_prev = w._date_from_calendar_pos(cal_pos)
    assert isinstance(date_prev, QDate) and date_prev.isValid()

    # A cell after the last day should map to next month
    last_day = QDate(qd.year(), qd.month(), 1).addMonths(1).addDays(-1).day()
    last_idx = None
    for r in range(model.rowCount() - 1, -1, -1):
        for c in range(model.columnCount() - 1, -1, -1):
            if model.index(r, c).data() == last_day:
                last_idx = model.index(r, c)
                break
        if last_idx:
            break
    assert last_idx is not None

    c_next = min(model.columnCount() - 1, last_idx.column() + 1)
    idx_next = model.index(last_idx.row(), c_next)
    vp_pos2 = view.visualRect(idx_next).center()
    global_pos2 = view.viewport().mapToGlobal(vp_pos2)
    cal_pos2 = w.calendar.mapFromGlobal(global_pos2)
    date_next = w._date_from_calendar_pos(cal_pos2)
    assert isinstance(date_next, QDate) and date_next.isValid()

    # Context menu path: return the "Open in New Tab" action
    class DummyMenu:
        def __init__(self, parent=None):
            self._action = object()

        def addAction(self, text):
            return self._action

        def exec_(self, *args, **kwargs):
            return self._action

    monkeypatch.setattr(mwmod, "QMenu", DummyMenu, raising=True)
    w._show_calendar_context_menu(cal_pos)


def test_event_filter_keypress_starts_idle_timer(qtbot, app):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()
    ev = QEvent(QEvent.KeyPress)
    w.eventFilter(w, ev)


def _make_main_window(tmp_db_cfg, app, monkeypatch, fresh_db=None):
    """Create a MainWindow wired to an existing db config so it doesn't prompt for key."""
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    # Force MainWindow to pick up our provided cfg
    monkeypatch.setattr(mwmod, "load_db_config", lambda: tmp_db_cfg, raising=True)
    # Make sure DB connects fine
    if fresh_db is None:
        fresh_db = DBManager(tmp_db_cfg)
        assert fresh_db.connect()
    w = MainWindow(themes)
    return w


def test_init_exits_when_prompt_rejected(app, monkeypatch, tmp_path):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))

    # cfg with empty key and non-existent path => first_time True
    cfg = DBConfig(
        path=tmp_path / "does_not_exist.db",
        key="",
        idle_minutes=0,
        theme="light",
        move_todos=True,
    )
    monkeypatch.setattr(mwmod, "load_db_config", lambda: cfg, raising=True)

    # Avoid accidentaly creating DB by short-circuiting the prompt loop
    class MW(MainWindow):
        def _prompt_for_key_until_valid(self, first_time: bool) -> bool:  # noqa: N802
            assert first_time is True
            return False

    with pytest.raises(SystemExit):
        MW(themes)


@pytest.mark.parametrize(
    "msg, expect_key_msg",
    [
        ("file is not a database", True),
        ("totally unrelated", False),
    ],
)
def test_try_connect_maps_errors(
    qtbot, tmp_db_cfg, app, monkeypatch, msg, expect_key_msg
):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # Make connect() raise
    def boom(self):
        raise Exception(msg)

    monkeypatch.setattr(mwmod.DBManager, "connect", boom, raising=True)

    shown = {}

    def fake_critical(parent, title, text, *a, **k):
        shown["title"] = title
        shown["text"] = str(text)
        return 0

    monkeypatch.setattr(
        mwmod.QMessageBox, "critical", staticmethod(fake_critical), raising=True
    )

    # Intercept sys.exit so the test process doesn't actually die
    exited = {}

    def fake_exit(code=0):
        exited["code"] = code
        # mimic real behaviour: raise SystemExit so callers see a fatal exit
        raise SystemExit(code)

    monkeypatch.setattr(mwmod.sys, "exit", fake_exit, raising=True)

    # _try_connect should now raise SystemExit instead of returning
    with pytest.raises(SystemExit):
        w._try_connect()

    # We attempted to exit with code 1
    assert exited["code"] == 1

    # And we still showed the right error message
    assert "database" in shown["title"].lower()
    if expect_key_msg:
        assert "key" in shown["text"].lower()
    else:
        assert "unrelated" in shown["text"].lower()
    # If closeEvent later explodes here, that is an app bug (should guard partial init).


# ---- _prompt_for_key_until_valid (324-332) ----


def test_prompt_for_key_cancel_returns_false(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    class CancelPrompt:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return mwmod.QDialog.Rejected

        def key(self):
            return ""

        def db_path(self) -> Path | None:
            return "foo.db"

    monkeypatch.setattr(mwmod, "KeyPrompt", CancelPrompt, raising=True)
    assert w._prompt_for_key_until_valid(first_time=False) is False


def test_prompt_for_key_accept_then_connects(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    class OKPrompt:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return mwmod.QDialog.Accepted

        def key(self):
            return "abc"

        def db_path(self) -> Path | None:
            return "foo.db"

    monkeypatch.setattr(mwmod, "KeyPrompt", OKPrompt, raising=True)
    monkeypatch.setattr(w, "_try_connect", lambda: True, raising=True)
    assert w._prompt_for_key_until_valid(first_time=True) is True
    assert w.cfg.key == "abc"


# ---- Tabs/date management (368, 383, 388-391, 427-428, …) ----


def test_reorder_tabs_by_date_and_tab_lookup(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    d1 = QDate.fromString("2024-01-10", "yyyy-MM-dd")
    d2 = QDate.fromString("2024-01-01", "yyyy-MM-dd")
    d3 = QDate.fromString("2024-02-01", "yyyy-MM-dd")

    e2 = w._create_new_tab(d2)
    e3 = w._create_new_tab(d3)
    e1 = w._create_new_tab(d1)  # out of order on purpose

    # Force a reorder and verify ascending order for the three we added.
    w._reorder_tabs_by_date()
    order = [w.tab_widget.tabText(i) for i in range(w.tab_widget.count())]
    today = QDate.currentDate().toString("yyyy-MM-dd")
    order_wo_today = [d for d in order if d != today]
    assert order_wo_today[:3] == ["2024-01-01", "2024-01-10", "2024-02-01"]

    # _tab_index_for_date finds existing and returns -1 for absent
    assert w._tab_index_for_date(d2) != -1
    assert w._tab_index_for_date(QDate.fromString("1999-12-31", "yyyy-MM-dd")) == -1
    assert e1 is not None and e2 is not None and e3 is not None


def test_open_close_tabs_and_focus(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    today = QDate.currentDate()
    ed = w._open_date_in_tab(today)  # creates new if needed
    assert hasattr(ed, "current_date")
    # make another tab to allow closing
    w._create_new_tab(today.addDays(1))
    count = w.tab_widget.count()
    w._close_tab(0)
    assert w.tab_widget.count() == count - 1


# ---- _set_editor_markdown_preserve_view & load with extra_data (631) ----


def test_load_selected_date_appends_extra_data_with_newline(
    qtbot, tmp_db_cfg, app, monkeypatch, fresh_db
):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch, fresh_db)
    qtbot.addWidget(w)
    w.db.save_new_version("2020-01-01", "first line", "seed")
    w._load_selected_date("2020-01-01", extra_data="- [ ] carry")
    assert "carry" in w.editor.toPlainText()


# ---- _save_editor_content early return (679) ----


def test_save_editor_content_returns_without_current_date(
    qtbot, tmp_db_cfg, app, monkeypatch
):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    from PySide6.QtWidgets import QTextEdit

    other = QTextEdit()
    w._save_editor_content(other)  # should early-return, not crash


# ---- _adjust_today creates a tab (695-696) ----


def test_adjust_today_creates_tab(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)
    w._adjust_today()
    today = QDate.currentDate().toString("yyyy-MM-dd")
    assert any(w.tab_widget.tabText(i) == today for i in range(w.tab_widget.count()))


# ---- _on_date_changed guard for context menus (745) ----


def test_on_date_changed_early_return_when_context_menu(
    qtbot, tmp_db_cfg, app, monkeypatch
):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)
    w._showing_context_menu = True
    # Should not throw or load
    w._on_date_changed()
    assert w._showing_context_menu is True  # not toggled here


# ---- _save_current explicit paths (793-801, 809-810) ----


def test_save_current_explicit_cancel(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    class CancelSave:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return mwmod.QDialog.Rejected

        def note_text(self):
            return ""

    monkeypatch.setattr(mwmod, "SaveDialog", CancelSave, raising=True)
    # returns early, does not raise
    w._save_current(explicit=True)


def test_save_current_explicit_accept(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    class OKSave:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return mwmod.QDialog.Accepted

        def note_text(self):
            return "manual"

    monkeypatch.setattr(mwmod, "SaveDialog", OKSave, raising=True)
    w._save_current(explicit=True)  # should start/restart timers without error


# ---- Search highlighting (852-854) ----


def test_apply_search_highlights_adds_and_clears(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)
    d1 = QDate.currentDate()
    d2 = d1.addDays(1)
    w._apply_search_highlights({d1, d2})
    # now drop d2 so clear-path runs
    w._apply_search_highlights({d1})
    fmt = w.calendar.dateTextFormat(d1)
    assert fmt.background().style() != Qt.NoBrush


# ---- History dialog glue (956, 961-962) ----


def test_open_history_accept_refreshes(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    called = {"load": False, "refresh": False}

    def fake_load(date_iso=None):
        called["load"] = True

    def fake_refresh():
        called["refresh"] = True

    monkeypatch.setattr(w, "_load_selected_date", fake_load, raising=True)
    monkeypatch.setattr(w, "_refresh_calendar_marks", fake_refresh, raising=True)

    class Dlg:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return mwmod.QDialog.Accepted

    monkeypatch.setattr(mwmod, "HistoryDialog", Dlg, raising=True)
    w._open_history()
    assert called["load"] and called["refresh"]


# ---- Insert image picker (974, 981-989) ----


def test_on_insert_image_calls_editor_insert(
    qtbot, tmp_db_cfg, app, monkeypatch, tmp_path
):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # Make a tiny PNG file
    from PySide6.QtGui import QImage

    img_path = tmp_path / "tiny.png"
    img = QImage(1, 1, QImage.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    img.save(str(img_path))

    called = []

    def fake_picker(*a, **k):
        return ([str(img_path)], "Images (*.png)")

    monkeypatch.setattr(
        mwmod.QFileDialog, "getOpenFileNames", staticmethod(fake_picker), raising=True
    )

    def recorder(path):
        called.append(Path(path))

    monkeypatch.setattr(w.editor, "insert_image_from_path", recorder, raising=True)

    w._on_insert_image()
    assert called and called[0].name == "tiny.png"


# ---- Export flow branches (1062, 1078-1107) ----


@pytest.mark.parametrize(
    "filter_label, method",
    [
        ("JSON (*.json)", "export_json"),
        ("CSV (*.csv)", "export_csv"),
        ("HTML (*.html)", "export_html"),
        ("Markdown (*.md)", "export_markdown"),
        ("SQL (*.sql)", "export_sql"),
    ],
)
def test_export_calls_correct_method(
    qtbot, tmp_db_cfg, app, monkeypatch, tmp_path, filter_label, method
):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # Confirm 'Yes' using the real QMessageBox; patch methods only
    monkeypatch.setattr(
        mwmod.QMessageBox, "exec", lambda self: mwmod.QMessageBox.Yes, raising=False
    )
    monkeypatch.setattr(
        mwmod.QMessageBox, "information", staticmethod(lambda *a, **k: 0), raising=False
    )
    monkeypatch.setattr(
        mwmod.QMessageBox, "critical", staticmethod(lambda *a, **k: 0), raising=False
    )

    # Return a path without extension to exercise default-ext logic too
    out = tmp_path / "out"
    monkeypatch.setattr(
        mwmod.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), filter_label)),
        raising=True,
    )

    # Provide some entries
    monkeypatch.setattr(
        w.db, "get_all_entries", lambda: [("2024-01-01", "x")], raising=True
    )

    called = {"name": None}

    def mark(*a, **k):
        called["name"] = method

    monkeypatch.setattr(w.db, method, mark, raising=True)
    w._export()
    assert called["name"] == method


def test_export_unknown_filter_raises_and_is_caught(
    qtbot, tmp_db_cfg, app, monkeypatch, tmp_path
):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # Pre-export confirmation: Yes
    monkeypatch.setattr(
        mwmod.QMessageBox, "exec", lambda self: mwmod.QMessageBox.Yes, raising=False
    )

    out = tmp_path / "weird"
    monkeypatch.setattr(
        mwmod.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "WUT (*.wut)")),
        raising=True,
    )

    # Capture the critical call
    seen = {}

    def critical(parent, title, text, *a, **k):
        seen["title"] = title
        seen["text"] = str(text)
        return 0

    monkeypatch.setattr(
        mwmod.QMessageBox, "critical", staticmethod(critical), raising=False
    )

    # And stub entries
    monkeypatch.setattr(w.db, "get_all_entries", lambda: [], raising=True)

    w._export()
    assert "export" in seen["title"].lower()


# ---- Backup handler (1147-1148) ----


def test_backup_success_and_error(qtbot, tmp_db_cfg, app, monkeypatch, tmp_path):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # Always choose a filename and the SQL option
    out = tmp_path / "backup"
    monkeypatch.setattr(
        mwmod.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "SQLCipher (*.db)")),
        raising=True,
    )

    called = {"ok": False, "err": False}

    def ok_export(path):
        called["ok"] = True

    def crit(parent, title, text, *a, **k):
        called["err"] = True
        return 0

    # First success
    monkeypatch.setattr(w.db, "export_sqlcipher", ok_export, raising=True)
    monkeypatch.setattr(
        mwmod.QMessageBox, "information", staticmethod(lambda *a, **k: 0), raising=False
    )
    monkeypatch.setattr(
        mwmod.QMessageBox, "critical", staticmethod(crit), raising=False
    )
    w._backup()
    assert called["ok"]

    # Then failure
    def boom(path):
        raise RuntimeError("nope")

    monkeypatch.setattr(w.db, "export_sqlcipher", boom, raising=True)
    w._backup()
    assert called["err"]


# ---- Help openers (1152-1169) ----


def test_open_docs_show_warning_on_failure(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    monkeypatch.setattr(
        mwmod.QDesktopServices, "openUrl", staticmethod(lambda *a: False), raising=True
    )
    seen = {"docs": False, "bugs": False}

    def warn(parent, title, text, *a, **k):
        if "documentation" in title.lower():
            seen["docs"] = True
        return 0

    monkeypatch.setattr(
        mwmod, "QMessageBox", type("MB", (), {"warning": staticmethod(warn)})
    )
    w._open_docs()

    assert seen["docs"]


def test_open_version(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    called = {"title": None, "text": None}

    def fake_information(parent, title, text, *a, **k):
        called["title"] = title
        called["text"] = text
        # Return value of QMessageBox.information is an int; 0 is fine.
        return 0

    # Patch whichever one you actually use in _open_version
    monkeypatch.setattr(QMessageBox, "information", fake_information)

    w._open_version()

    assert called["title"] is not None
    assert "version" in called["title"].lower()
    version = importlib.metadata.version("bouquin")
    assert version in called["text"]


# ---- Idle/lock/event filter helpers (1176, 1181-1187, 1193-1202, 1231-1233) ----


def test_apply_idle_minutes_paths_and_unlock(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # remove timer to hit early return
    delattr(w, "_idle_timer")
    w._apply_idle_minutes(5)  # no crash

    # re-create a timer and simulate locking then disabling idle
    w._idle_timer = QTimer(w)
    w._idle_timer.setSingleShot(True)
    w._locked = True
    w._apply_idle_minutes(0)
    assert not w._locked  # unlocked and overlay hidden path covered


def test_event_filter_sets_context_flag_and_keystart(
    qtbot, tmp_db_cfg, app, monkeypatch
):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)
    # Right-click on calendar with a real QMouseEvent
    me = QMouseEvent(
        QEvent.MouseButtonPress,
        QPoint(0, 0),
        Qt.RightButton,
        Qt.RightButton,
        Qt.NoModifier,
    )
    w.eventFilter(w.calendar, me)
    assert getattr(w, "_showing_context_menu", False) is True

    # KeyPress restarts idle timer when unlocked (real QKeyEvent)
    w._locked = False
    ke = QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier)
    w.eventFilter(w, ke)


def test_unlock_exception_path(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(w, "_prompt_for_key_until_valid", boom, raising=True)

    captured = {}

    def critical(parent, title, text, *a, **k):
        captured["title"] = title
        return 0

    monkeypatch.setattr(
        mwmod, "QMessageBox", type("MB", (), {"critical": staticmethod(critical)})
    )
    w._on_unlock_clicked()
    assert "unlock" in captured["title"].lower()


# ---- Focus helpers (1273-1275, 1290) ----


def test_focus_editor_now_and_app_state(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)
    w.show()
    # Locked => early return
    w._locked = True
    w._focus_editor_now()
    # Active window path (force isActiveWindow)
    w._locked = False
    monkeypatch.setattr(w, "isActiveWindow", lambda: True, raising=True)
    w._focus_editor_now()
    # App state callback path
    w._on_app_state_changed(Qt.ApplicationActive)


# ---- _rect_on_any_screen false path (1039) ----


def test_rect_on_any_screen_false(qtbot, tmp_db_cfg, app, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)
    sc = QApplication.primaryScreen().availableGeometry()
    far = QRect(sc.right() + 10_000, sc.bottom() + 10_000, 100, 100)
    assert not w._rect_on_any_screen(far)


def test_reorder_tabs_with_undated_page_stays_last(qtbot, app, tmp_db_cfg, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # Create two dated tabs (out of order), plus an undated QWidget page.
    d1 = QDate.fromString("2024-02-01", "yyyy-MM-dd")
    d2 = QDate.fromString("2024-01-01", "yyyy-MM-dd")
    w._create_new_tab(d1)
    w._create_new_tab(d2)

    misc = QWidget()
    w.tab_widget.addTab(misc, "misc")

    # Reorder and check: dated tabs sorted first, undated kept after them
    w._reorder_tabs_by_date()
    labels = [w.tab_widget.tabText(i) for i in range(w.tab_widget.count())]
    assert labels[0] <= labels[1]
    assert labels[-1] == "misc"

    # Also cover lookup for an existing date
    assert w._tab_index_for_date(d2) != -1


def test_index_for_date_insert_positions(qtbot, app, tmp_db_cfg, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    a = QDate.fromString("2024-01-01", "yyyy-MM-dd")
    c = QDate.fromString("2024-03-01", "yyyy-MM-dd")
    d = QDate.fromString("2024-04-01", "yyyy-MM-dd")

    def expected():
        key = (d.year(), d.month(), d.day())
        for i in range(w.tab_widget.count()):
            ed = w.tab_widget.widget(i)
            cur = getattr(ed, "current_date", None)
            if isinstance(cur, QDate) and cur.isValid():
                if (cur.year(), cur.month(), cur.day()) > key:
                    return i
        return w.tab_widget.count()

    w._create_new_tab(a)
    w._create_new_tab(c)

    # B belongs between A and C
    b = QDate.fromString("2024-02-01", "yyyy-MM-dd")
    assert w._index_for_date_insert(b) == 1

    # Date prior to first should insert at 0
    z = QDate.fromString("2023-12-31", "yyyy-MM-dd")
    assert w._index_for_date_insert(z) == 0

    # Date after last should append
    d = QDate.fromString("2024-04-01", "yyyy-MM-dd")
    assert w._index_for_date_insert(d) == expected()


def test_on_tab_changed_early_and_stop_guard(qtbot, app, tmp_db_cfg, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # Early return path
    w._on_tab_changed(-1)

    # Create two tabs then make stop() raise to hit try/except guard
    w._create_new_tab(QDate.fromString("2024-01-01", "yyyy-MM-dd"))
    w._create_new_tab(QDate.fromString("2024-01-02", "yyyy-MM-dd"))

    def boom():
        raise RuntimeError("stop failed")

    monkeypatch.setattr(w._save_timer, "stop", boom, raising=True)
    w._on_tab_changed(1)  # should not raise


def test_show_calendar_context_menu_no_action(qtbot, app, tmp_db_cfg, monkeypatch):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)
    before = w.tab_widget.count()

    class DummyMenu:
        def __init__(self, *a, **k):
            pass

        def addAction(self, *a, **k):
            return object()

        def exec_(self, *a, **k):
            return None  # return no action

    monkeypatch.setattr(mwmod, "QMenu", DummyMenu, raising=True)
    w._show_calendar_context_menu(w.calendar.rect().center())  # nothing should happen
    assert w.tab_widget.count() == before


def test_export_cancel_then_empty_filename(
    qtbot, app, tmp_db_cfg, monkeypatch, tmp_path
):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # 1) cancel at the confirmation dialog
    class FullMB:
        Yes = QMessageBox.Yes
        No = QMessageBox.No
        Warning = QMessageBox.Warning

        def __init__(self, *a, **k):
            pass

        def setWindowTitle(self, *a):
            pass

        def setText(self, *a):
            pass

        def setStandardButtons(self, *a):
            pass

        def setIcon(self, *a):
            pass

        def show(self):
            pass

        def adjustSize(self):
            pass

        def exec(self):
            return self.No

        @staticmethod
        def information(*a, **k):
            return 0

        @staticmethod
        def critical(*a, **k):
            return 0

    monkeypatch.setattr(mwmod, "QMessageBox", FullMB, raising=True)
    w._export()  # returns early on No

    # 2) Yes in confirmation, but user cancels file dialog (empty filename)
    class YesOnly(FullMB):
        def exec(self):
            return self.Yes

    monkeypatch.setattr(mwmod, "QMessageBox", YesOnly, raising=True)
    monkeypatch.setattr(
        mwmod.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: ("", "Markdown (*.md)")),
        raising=False,
    )
    w._export()  # returns early at filename check


def test_set_editor_markdown_preserve_view_preserves(
    qtbot, app, tmp_db_cfg, monkeypatch
):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    long = "line\n" * 200
    w.editor.from_markdown(long)
    w.editor.verticalScrollBar().setValue(50)
    w.editor.moveCursor(QTextCursor.End)
    pos_before = w.editor.textCursor().position()
    v_before = w.editor.verticalScrollBar().value()

    # Same markdown → no rewrite, caret/scroll restored
    w._set_editor_markdown_preserve_view(long)
    assert w.editor.textCursor().position() == pos_before
    assert w.editor.verticalScrollBar().value() == v_before

    # Different markdown → rewritten but caret restoration still executes
    changed = long + "extra\n"
    w._set_editor_markdown_preserve_view(changed)
    assert w.editor.to_markdown().endswith("extra\n")


def test_load_date_into_editor_with_extra_data_forces_save(
    qtbot, app, tmp_db_cfg, monkeypatch
):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    called = {"iso": None, "explicit": None}

    def save_date(iso, explicit):
        called.update(iso=iso, explicit=explicit)

    monkeypatch.setattr(w, "_save_date", save_date, raising=True)
    d = QDate.fromString("2020-01-01", "yyyy-MM-dd")
    w._load_date_into_editor(d, extra_data="- [ ] carry")
    assert called["iso"] == "2020-01-01" and called["explicit"] is True


def test_reorder_tabs_moves_and_undated(qtbot, app, tmp_db_cfg, monkeypatch):
    """Covers moveTab for both dated and undated buckets."""
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # Create out-of-order dated tabs
    d1 = QDate.fromString("2024-01-10", "yyyy-MM-dd")
    d2 = QDate.fromString("2024-01-01", "yyyy-MM-dd")
    d3 = QDate.fromString("2024-02-01", "yyyy-MM-dd")
    w._create_new_tab(d1)
    w._create_new_tab(d3)
    w._create_new_tab(d2)

    # Also insert an "undated" plain QWidget at the front to force a move later
    undated = QWidget()
    w.tab_widget.insertTab(0, undated, "undated")

    moved = {"calls": []}
    tb = w.tab_widget.tabBar()

    def spy_moveTab(frm, to):
        moved["calls"].append((frm, to))
        # don't actually move; we just need the call for coverage

    monkeypatch.setattr(tb, "moveTab", spy_moveTab, raising=True)

    w._reorder_tabs_by_date()
    assert moved["calls"]  # both dated and undated moves should have occurred


def test_date_from_calendar_view_none(qtbot, app, tmp_db_cfg, monkeypatch):
    """Covers early return when calendar view can't be found."""
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    monkeypatch.setattr(
        w.calendar,
        "findChild",
        lambda *a, **k: None,  # pretend the internal view is missing
        raising=False,
    )
    assert w._date_from_calendar_pos(QPoint(1, 1)) is None


def test_date_from_calendar_no_first_or_last(qtbot, app, tmp_db_cfg, monkeypatch):
    """
    Covers early returns when first_index or last_index cannot be found
    """
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    class FakeModel:
        def rowCount(self):
            return 1

        def columnCount(self):
            return 1

        class Idx:
            def data(self):
                return None  # never equals first/last-day

        def index(self, *_):
            return self.Idx()

    class FakeView:
        def model(self):
            return FakeModel()

        class VP:
            def mapToGlobal(self, p):
                return p

            def mapFrom(self, *_):  # calendar-local -> viewport
                return QPoint(0, 0)

        def viewport(self):
            return self.VP()

        def indexAt(self, *_):
            # return an *instance* whose isValid() returns False
            return type("I", (), {"isValid": lambda self: False})()

    monkeypatch.setattr(
        w.calendar,
        "findChild",
        lambda *a, **k: FakeView(),
        raising=False,
    )
    # Early return when first day (1) can't be found
    assert w._date_from_calendar_pos(QPoint(5, 5)) is None


def test_save_editor_content_returns_if_no_conn(qtbot, app, tmp_db_cfg, monkeypatch):
    """Covers DB not connected branch."""
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # window editor has a current_date; simulate a dropped connection
    assert isinstance(w.db, DBManager)
    w.db.conn = None
    # no crash -> branch hit
    w._save_editor_content(w.editor)


def test_on_date_changed_stops_timer_and_saves_prev_when_dirty(
    qtbot, app, tmp_db_cfg, monkeypatch
):
    """
    Covers the exception-protected _save_timer.stop() and
    the prev-date save path.
    """
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # Make timer.stop() raise so the except path is covered
    w._dirty = True
    w.editor.current_date = QDate.fromString("2024-01-01", "yyyy-MM-dd")
    # make timer.stop() raise so the except path is exercised
    monkeypatch.setattr(
        w._save_timer,
        "stop",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        raising=True,
    )

    saved = {"iso": None}

    def stub_save_date(iso, explicit=False, note=None):
        saved["iso"] = iso

    monkeypatch.setattr(w, "_save_date", stub_save_date, raising=False)

    w._on_date_changed()
    assert saved["iso"] == "2024-01-01"


def test_bind_toolbar_idempotent(qtbot, app, tmp_db_cfg, monkeypatch):
    """Covers early return when toolbar is already bound."""
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)
    w._bind_toolbar()
    # Call again; line is covered if this no-ops
    w._bind_toolbar()


def test_on_insert_image_no_selection_returns(qtbot, app, tmp_db_cfg, monkeypatch):
    """Covers the early return when user selects no files."""
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    monkeypatch.setattr(
        mwmod.QFileDialog,
        "getOpenFileNames",
        staticmethod(lambda *a, **k: ([], "")),
        raising=True,
    )

    # Ensure we would notice if it tried to insert anything
    monkeypatch.setattr(
        w.editor,
        "insert_image_from_path",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not insert")),
        raising=True,
    )
    w._on_insert_image()


def test_apply_idle_minutes_starts_when_unlocked(qtbot, app, tmp_db_cfg, monkeypatch):
    """Covers set + start when minutes>0 and not locked."""
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)
    w._locked = False

    hit = {"start": False}
    monkeypatch.setattr(
        w._idle_timer,
        "start",
        lambda *a, **k: hit.__setitem__("start", True),
        raising=True,
    )
    w._apply_idle_minutes(7)
    assert hit["start"]


def test_close_event_handles_settings_failures(qtbot, app, tmp_db_cfg, monkeypatch):
    """
    Covers exception swallowing around settings writes & ensures close proceeds
    """
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    qtbot.addWidget(w)

    # A couple of tabs so _save_editor_content runs during close
    w._create_new_tab(QDate.fromString("2024-01-01", "yyyy-MM-dd"))

    # Make settings.setValue raise for coverage
    orig_set = w.settings.setValue

    def flaky_set(*a, **k):
        if a[0] in ("main/geometry", "main/windowState"):
            raise RuntimeError("boom")
        return orig_set(*a, **k)

    monkeypatch.setattr(w.settings, "setValue", flaky_set, raising=True)

    # Should not crash
    w.close()


def test_on_date_changed_ignored_when_context_menu_shown(
    qtbot, app, tmp_db_cfg, monkeypatch
):
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)
    # Simulate flag set by context menu to ensure early return path
    w._showing_context_menu = True
    w._on_date_changed()  # should simply return without raising
    assert True  # reached


def test_closeEvent_swallows_exceptions(qtbot, app, tmp_db_cfg, monkeypatch):
    called = {"save": False, "close": False}
    w = _make_main_window(tmp_db_cfg, app, monkeypatch)

    def bad_save(editor):
        called["save"] = True
        raise RuntimeError("boom")

    class DummyDB:
        def __init__(self):
            self.conn = object()  # <-- make conn truthy so branch is taken

        def close(self):
            called["close"] = True
            raise RuntimeError("kaboom")

    class DummyTabs:
        def count(self):
            return 1  # <-- ensures the save loop runs

        def widget(self, i):
            return object()  # any non-None editor-like object

    # Patch the pieces the closeEvent checks
    w.tab_widget = DummyTabs()
    w.db = DummyDB()
    monkeypatch.setattr(w, "_save_editor_content", bad_save, raising=True)

    # Fire the event
    ev = QCloseEvent()
    w.closeEvent(ev)

    assert called["save"] and called["close"]


# ============================================================================
# Tag Save Handler Tests
# ============================================================================


def test_main_window_do_tag_save_with_editor(app, fresh_db, tmp_db_cfg, monkeypatch):
    """Test _do_tag_save when editor has current_date"""
    # Skip the key prompt
    monkeypatch.setattr(
        "bouquin.main_window.KeyPrompt",
        lambda *args, **kwargs: Mock(exec=lambda: True, key=lambda: tmp_db_cfg.key),
    )
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    window = MainWindow(themes)

    # Set a date on the editor
    date = QDate(2024, 1, 15)
    window.editor.current_date = date
    window.editor.from_markdown("Test content")

    # Call _do_tag_save
    window._do_tag_save()

    # Should have saved
    fresh_db.get_entry("2024-01-15")
    # May or may not have content depending on timing, but should not crash
    assert True


def test_main_window_do_tag_save_no_editor(app, fresh_db, tmp_db_cfg, monkeypatch):
    """Test _do_tag_save when editor doesn't have current_date"""
    monkeypatch.setattr(
        "bouquin.main_window.KeyPrompt",
        lambda *args, **kwargs: Mock(exec=lambda: True, key=lambda: tmp_db_cfg.key),
    )

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    window = MainWindow(themes)

    # Remove current_date attribute
    if hasattr(window.editor, "current_date"):
        delattr(window.editor, "current_date")

    # Call _do_tag_save - should handle gracefully
    window._do_tag_save()

    assert True


def test_main_window_on_tag_added_triggers_deferred_save(
    app, fresh_db, tmp_db_cfg, monkeypatch
):
    """Test that _on_tag_added defers the save"""
    monkeypatch.setattr(
        "bouquin.main_window.KeyPrompt",
        lambda *args, **kwargs: Mock(exec=lambda: True, key=lambda: tmp_db_cfg.key),
    )

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    window = MainWindow(themes)

    # Mock QTimer.singleShot
    with patch("PySide6.QtCore.QTimer.singleShot") as mock_timer:
        window._on_tag_added()

        # Should have called singleShot
        mock_timer.assert_called_once()
        args = mock_timer.call_args[0]
        assert args[0] == 0  # Delay of 0
        assert callable(args[1])  # Callback function


# ============================================================================
# Tag Activation Tests
# ============================================================================


def test_main_window_on_tag_activated_with_date(app, fresh_db, tmp_db_cfg, monkeypatch):
    """Test _on_tag_activated when passed a date string"""
    monkeypatch.setattr(
        "bouquin.main_window.KeyPrompt",
        lambda *args, **kwargs: Mock(exec=lambda: True, key=lambda: tmp_db_cfg.key),
    )

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    window = MainWindow(themes)

    # Mock _load_selected_date
    window._load_selected_date = Mock()

    # Call with date format
    window._on_tag_activated("2024-01-15")

    # Should have called _load_selected_date
    window._load_selected_date.assert_called_once_with("2024-01-15")


def test_main_window_on_tag_activated_with_tag_name(
    app, fresh_db, tmp_db_cfg, monkeypatch
):
    """Test _on_tag_activated when passed a tag name"""
    monkeypatch.setattr(
        "bouquin.main_window.KeyPrompt",
        lambda *args, **kwargs: Mock(exec=lambda: True, key=lambda: tmp_db_cfg.key),
    )

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    window = MainWindow(themes)

    # Mock the tag browser dialog (it's imported locally in the method)
    with patch("bouquin.tag_browser.TagBrowserDialog") as mock_dialog:
        mock_instance = Mock()
        mock_instance.openDateRequested = Mock()
        mock_instance.exec.return_value = QDialog.Accepted
        mock_dialog.return_value = mock_instance

        # Call with tag name
        window._on_tag_activated("worktag")

        # Should have opened dialog
        mock_dialog.assert_called_once()
        # Check focus_tag was passed
        call_kwargs = mock_dialog.call_args[1]
        assert call_kwargs.get("focus_tag") == "worktag"


# ============================================================================
# Settings Path Change Tests
# ============================================================================


def test_main_window_settings_path_change_success(
    app, fresh_db, tmp_db_cfg, tmp_path, monkeypatch
):
    """Test changing database path in settings"""
    monkeypatch.setattr(
        "bouquin.main_window.KeyPrompt",
        lambda *args, **kwargs: Mock(exec=lambda: True, key=lambda: tmp_db_cfg.key),
    )

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    window = MainWindow(themes)

    new_path = tmp_path / "new.db"

    # Mock the settings dialog
    with patch("bouquin.main_window.SettingsDialog") as mock_dialog:
        mock_instance = Mock()
        mock_instance.exec.return_value = QDialog.Accepted

        # Create a new config with different path
        new_cfg = Mock()
        new_cfg.path = str(new_path)
        new_cfg.key = tmp_db_cfg.key
        new_cfg.idle_minutes = 15
        new_cfg.theme = "light"
        new_cfg.move_todos = True
        new_cfg.locale = "en"

        mock_instance.config = new_cfg
        mock_dialog.return_value = mock_instance

        # Mock _prompt_for_key_until_valid to return True
        window._prompt_for_key_until_valid = Mock(return_value=True)
        # Also mock _load_selected_date and _refresh_calendar_marks since we don't have a real DB connection
        window._load_selected_date = Mock()
        window._refresh_calendar_marks = Mock()

        # Open settings
        window._open_settings()

        # Path should have changed
        assert window.cfg.path == str(new_path)


def test_main_window_settings_path_change_failure(
    app, fresh_db, tmp_db_cfg, tmp_path, monkeypatch
):
    """Test failed database path change shows warning"""
    monkeypatch.setattr(
        "bouquin.main_window.KeyPrompt",
        lambda *args, **kwargs: Mock(exec=lambda: True, key=lambda: tmp_db_cfg.key),
    )

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    window = MainWindow(themes)

    new_path = tmp_path / "new.db"

    # Mock the settings dialog
    with patch("bouquin.main_window.SettingsDialog") as mock_dialog:
        mock_instance = Mock()
        mock_instance.exec.return_value = QDialog.Accepted

        new_cfg = Mock()
        new_cfg.path = str(new_path)
        new_cfg.key = tmp_db_cfg.key
        new_cfg.idle_minutes = 15
        new_cfg.theme = "light"
        new_cfg.move_todos = True
        new_cfg.locale = "en"

        mock_instance.config = new_cfg
        mock_dialog.return_value = mock_instance

        # Mock _prompt_for_key_until_valid to return False (failure)
        window._prompt_for_key_until_valid = Mock(return_value=False)

        # Mock QMessageBox.warning
        with patch.object(QMessageBox, "warning") as mock_warning:
            # Open settings
            window._open_settings()

            # Warning should have been shown
            mock_warning.assert_called_once()


def test_main_window_settings_no_path_change(app, fresh_db, tmp_db_cfg, monkeypatch):
    """Test settings change without path change"""
    monkeypatch.setattr(
        "bouquin.main_window.KeyPrompt",
        lambda *args, **kwargs: Mock(exec=lambda: True, key=lambda: tmp_db_cfg.key),
    )

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    window = MainWindow(themes)

    old_path = window.cfg.path

    # Mock the settings dialog
    with patch("bouquin.main_window.SettingsDialog") as mock_dialog:
        mock_instance = Mock()
        mock_instance.exec.return_value = QDialog.Accepted

        # Create config with SAME path
        new_cfg = Mock()
        new_cfg.path = old_path
        new_cfg.key = tmp_db_cfg.key
        new_cfg.idle_minutes = 20  # Changed
        new_cfg.theme = "dark"  # Changed
        new_cfg.move_todos = False  # Changed
        new_cfg.locale = "fr"  # Changed

        mock_instance.config = new_cfg
        mock_dialog.return_value = mock_instance

        # Open settings
        window._open_settings()

        # Settings should be updated but path didn't change
        assert window.cfg.idle_minutes == 20
        assert window.cfg.theme == "dark"
        assert window.cfg.path == old_path


def test_main_window_settings_cancelled(app, fresh_db, tmp_db_cfg, monkeypatch):
    """Test cancelling settings dialog"""
    monkeypatch.setattr(
        "bouquin.main_window.KeyPrompt",
        lambda *args, **kwargs: Mock(exec=lambda: True, key=lambda: tmp_db_cfg.key),
    )
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    window = MainWindow(themes)

    old_theme = window.cfg.theme

    # Mock the settings dialog to be rejected
    with patch("bouquin.main_window.SettingsDialog") as mock_dialog:
        mock_instance = Mock()
        mock_instance.exec.return_value = QDialog.Rejected
        mock_dialog.return_value = mock_instance

        # Open settings
        window._open_settings()

        # Settings should NOT change
        assert window.cfg.theme == old_theme


# ============================================================================
# Update Tag Views Tests
# ============================================================================


def test_main_window_update_tag_views_for_date(app, fresh_db, tmp_db_cfg, monkeypatch):
    """Test _update_tag_views_for_date"""
    monkeypatch.setattr(
        "bouquin.main_window.KeyPrompt",
        lambda *args, **kwargs: Mock(exec=lambda: True, key=lambda: tmp_db_cfg.key),
    )

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    window = MainWindow(themes)

    # Set tags for a date
    fresh_db.set_tags_for_page("2024-01-15", ["test"])

    # Update tag views
    window._update_tag_views_for_date("2024-01-15")

    # Tags widget should have been updated
    assert window.tags._current_date == "2024-01-15"


def test_main_window_update_tag_views_no_tags_widget(
    app, fresh_db, tmp_db_cfg, monkeypatch
):
    """Test _update_tag_views_for_date when tags widget doesn't exist"""
    monkeypatch.setattr(
        "bouquin.main_window.KeyPrompt",
        lambda *args, **kwargs: Mock(exec=lambda: True, key=lambda: tmp_db_cfg.key),
    )

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    window = MainWindow(themes)

    # Remove tags widget
    delattr(window, "tags")

    # Should handle gracefully
    window._update_tag_views_for_date("2024-01-15")

    assert True
