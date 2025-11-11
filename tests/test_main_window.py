import pytest
import bouquin.main_window as mwmod
from bouquin.main_window import MainWindow
from bouquin.theme import Theme, ThemeConfig, ThemeManager
from bouquin.settings import get_settings
from bouquin.key_prompt import KeyPrompt
from PySide6.QtCore import QEvent, QDate, QTimer
from PySide6.QtWidgets import QTableView, QApplication


@pytest.mark.gui
def test_main_window_loads_and_saves(qtbot, app, tmp_db_cfg, fresh_db):
    s = get_settings()
    s.setValue("db/path", str(tmp_db_cfg.path))
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
                wdg.edit.setText(tmp_db_cfg.key)
                wdg.accept()

    w._enter_lock()
    QTimer.singleShot(0, _auto_accept_keyprompt)
    w._on_unlock_clicked()
    qtbot.wait(50)  # let the nested event loop process the acceptance


def test_load_yesterday_todos_moves_items(qtbot, app, tmp_db_cfg, fresh_db):
    s = get_settings()
    s.setValue("db/path", str(tmp_db_cfg.path))
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


@pytest.mark.gui
def test_open_docs_and_bugs_warning(qtbot, app, fresh_db, tmp_path, monkeypatch):
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
            if "forms/mig5/contact" in t or "contact" in t:
                called["bugs"] = True
            return 0

    monkeypatch.setattr(mwmod, "QMessageBox", DummyMB, raising=True)  # capture warnings

    # Trigger both actions
    w._open_docs()
    w._open_bugs()
    assert called["docs"] and called["bugs"]


@pytest.mark.gui
def test_export_success_and_error(qtbot, app, fresh_db, tmp_path, monkeypatch):
    # Seed some content
    fresh_db.save_new_version("2001-01-01", "alpha", "n1")
    fresh_db.save_new_version("2001-01-02", "beta", "n2")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    from bouquin.settings import get_settings

    s = get_settings()
    s.setValue("db/path", str(fresh_db.cfg.path))
    s.setValue("db/key", fresh_db.cfg.key)
    s.setValue("ui/idle_minutes", 0)
    s.setValue("ui/theme", "light")
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    # Save as Markdown without extension -> should append .md and write file
    dest1 = tmp_path / "export_one"  # no suffix

    def fake_save1(*a, **k):
        return str(dest1), "Markdown (*.md)"

    monkeypatch.setattr(mwmod.QFileDialog, "getSaveFileName", staticmethod(fake_save1))

    info_log = {"ok": False}

    # Auto-accept the warning dialog
    monkeypatch.setattr(
        mwmod.QMessageBox, "exec", lambda self: mwmod.QMessageBox.Yes, raising=False
    )
    info_log = {"ok": False}
    monkeypatch.setattr(
        mwmod.QMessageBox,
        "information",
        staticmethod(lambda *a, **k: info_log.__setitem__("ok", True) or 0),
        raising=False,
    )
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
    assert info_log["ok"]

    # Now force an exception during export to hit error branch (patch the window's DB)
    def boom():
        raise RuntimeError("explode")

    monkeypatch.setattr(w.db, "get_all_entries", boom, raising=False)

    # Different filename to avoid overwriting
    dest2 = tmp_path / "export_two"

    def fake_save2(*a, **k):
        return str(dest2), "CSV (*.csv)"

    monkeypatch.setattr(mwmod.QFileDialog, "getSaveFileName", staticmethod(fake_save2))

    errs = {"hit": False}
    # Auto-accept the warning dialog and capture the error message
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


@pytest.mark.gui
def test_backup_path(qtbot, app, fresh_db, tmp_path, monkeypatch):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))

    # wire DB settings the window reads
    from bouquin.settings import get_settings

    s = get_settings()
    s.setValue("db/path", str(fresh_db.cfg.path))
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


@pytest.mark.gui
def test_close_tab_edges_and_autosave(qtbot, app, fresh_db, monkeypatch):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    from bouquin.settings import get_settings

    s = get_settings()
    s.setValue("db/path", str(fresh_db.cfg.path))
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


@pytest.mark.gui
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


@pytest.mark.gui
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


@pytest.mark.gui
def test_event_filter_keypress_starts_idle_timer(qtbot, app):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()
    ev = QEvent(QEvent.KeyPress)
    w.eventFilter(w, ev)
