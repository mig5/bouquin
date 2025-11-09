import types
import pytest
from PySide6.QtWidgets import QFileDialog
from PySide6.QtGui import QTextCursor


from bouquin.theme import ThemeManager, ThemeConfig, Theme
from bouquin.settings import get_settings
from bouquin.main_window import MainWindow
from bouquin.history_dialog import HistoryDialog


@pytest.mark.gui
def test_tabs_open_and_deduplicate(qtbot, app, tmp_db_cfg, fresh_db):
    # point to the temp encrypted DB
    s = get_settings()
    s.setValue("db/path", str(tmp_db_cfg.path))
    s.setValue("db/key", tmp_db_cfg.key)

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    # first tab is today's date
    date1 = w.calendar.selectedDate()
    initial_count = w.tab_widget.count()

    # opening the same date should NOT create a new tab
    w._open_date_in_tab(date1)
    assert w.tab_widget.count() == initial_count
    assert w.tab_widget.currentWidget().current_date == date1

    # opening a different date should create exactly one new tab
    date2 = date1.addDays(1)
    w._open_date_in_tab(date2)
    assert w.tab_widget.count() == initial_count + 1
    assert w.tab_widget.currentWidget().current_date == date2

    # jumping back to date1 just focuses the existing tab
    w._open_date_in_tab(date1)
    assert w.tab_widget.count() == initial_count + 1
    assert w.tab_widget.currentWidget().current_date == date1


@pytest.mark.gui
def test_toolbar_signals_dispatch_once_per_click(
    qtbot, app, tmp_db_cfg, fresh_db, monkeypatch
):
    s = get_settings()
    s.setValue("db/path", str(tmp_db_cfg.path))
    s.setValue("db/key", tmp_db_cfg.key)

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    tb = w.toolBar

    # Spy on the first tab's editor
    ed1 = w.current_editor()
    calls1 = {
        "bold": 0,
        "italic": 0,
        "strike": 0,
        "code": 0,
        "heading": 0,
        "bullets": 0,
        "numbers": 0,
        "checkboxes": 0,
    }

    def mk(key):
        def _spy(self, *a, **k):
            calls1[key] += 1

        return _spy

    ed1.apply_weight = types.MethodType(mk("bold"), ed1)
    ed1.apply_italic = types.MethodType(mk("italic"), ed1)
    ed1.apply_strikethrough = types.MethodType(mk("strike"), ed1)
    ed1.apply_code = types.MethodType(mk("code"), ed1)
    ed1.apply_heading = types.MethodType(mk("heading"), ed1)
    ed1.toggle_bullets = types.MethodType(mk("bullets"), ed1)
    ed1.toggle_numbers = types.MethodType(mk("numbers"), ed1)
    ed1.toggle_checkboxes = types.MethodType(mk("checkboxes"), ed1)

    # Click all the things once
    tb.boldRequested.emit()
    tb.italicRequested.emit()
    tb.strikeRequested.emit()
    tb.codeRequested.emit()
    tb.headingRequested.emit(24)
    tb.bulletsRequested.emit()
    tb.numbersRequested.emit()
    tb.checkboxesRequested.emit()

    assert all(v == 1 for v in calls1.values())  # fired once each

    # Switch to a new tab and make sure clicks go ONLY to the active editor
    date2 = w.calendar.selectedDate().addDays(1)
    w._open_date_in_tab(date2)
    ed2 = w.current_editor()
    calls2 = {"bold": 0}
    ed2.apply_weight = types.MethodType(
        lambda self: calls2.__setitem__("bold", calls2["bold"] + 1), ed2
    )

    tb.boldRequested.emit()
    assert calls1["bold"] == 1
    assert calls2["bold"] == 1

    w._open_date_in_tab(date2.addDays(-1))  # back to first tab
    tb.boldRequested.emit()
    assert calls1["bold"] == 2
    assert calls2["bold"] == 1


@pytest.mark.gui
def test_history_and_insert_image_not_duplicated(
    qtbot, app, tmp_db_cfg, fresh_db, monkeypatch, tmp_path
):
    s = get_settings()
    s.setValue("db/path", str(tmp_db_cfg.path))
    s.setValue("db/key", tmp_db_cfg.key)

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    # History dialog opens exactly once
    opened = {"count": 0}

    def fake_exec(self):
        opened["count"] += 1
        return 0  # Rejected

    monkeypatch.setattr(HistoryDialog, "exec", fake_exec, raising=False)
    w.toolBar.historyRequested.emit()
    assert opened["count"] == 1

    # Insert image: simulate user selecting one file, and ensure it's inserted once
    dummy = tmp_path / "x.png"
    dummy.write_bytes(b"\x89PNG\r\n\x1a\n")
    inserted = {"count": 0}
    ed = w.current_editor()

    def fake_insert(self, p):
        inserted["count"] += 1

    ed.insert_image_from_path = types.MethodType(fake_insert, ed)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *a, **k: ([str(dummy)], "Images (*.png)"),
        raising=False,
    )
    w.toolBar.insertImageRequested.emit()
    assert inserted["count"] == 1


@pytest.mark.gui
def test_highlighter_attached_after_text_load(qtbot, app, tmp_db_cfg, fresh_db):
    s = get_settings()
    s.setValue("db/path", str(tmp_db_cfg.path))
    s.setValue("db/key", tmp_db_cfg.key)

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    ed = w.current_editor()
    ed.from_markdown("**bold**\n- [ ] task\n~~strike~~")
    assert ed.highlighter is not None
    assert ed.highlighter.document() is ed.document()


@pytest.mark.gui
def test_findbar_works_for_current_tab(qtbot, app, tmp_db_cfg, fresh_db):
    s = get_settings()
    s.setValue("db/path", str(tmp_db_cfg.path))
    s.setValue("db/key", tmp_db_cfg.key)

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    # Tab 1 content
    ed1 = w.current_editor()
    ed1.from_markdown("alpha bravo charlie")
    w.findBar.show_bar()
    w.findBar.edit.setText("bravo")
    w.findBar.find_next()
    assert ed1.textCursor().selectedText() == "bravo"

    # Tab 2 content (contains the query too)
    date2 = w.calendar.selectedDate().addDays(1)
    w._open_date_in_tab(date2)
    ed2 = w.current_editor()
    ed2.from_markdown("x bravo y bravo z")
    ed2.moveCursor(QTextCursor.Start)
    w.findBar.find_next()
    assert ed2.textCursor().selectedText() == "bravo"
