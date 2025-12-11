import types

from bouquin.history_dialog import HistoryDialog
from bouquin.main_window import MainWindow
from bouquin.settings import get_settings
from bouquin.theme import Theme, ThemeConfig, ThemeManager
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFileDialog


def test_tabs_open_and_deduplicate(qtbot, app, tmp_db_cfg, fresh_db):
    # point to the temp encrypted DB
    s = get_settings()
    s.setValue("db/default_db", str(tmp_db_cfg.path))
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


def test_toolbar_signals_dispatch_once_per_click(
    qtbot, app, tmp_db_cfg, fresh_db, monkeypatch
):
    s = get_settings()
    s.setValue("db/default_db", str(tmp_db_cfg.path))
    s.setValue("db/key", tmp_db_cfg.key)

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    tb = w.toolBar

    # Spy on the first tab's editor
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

    w.editor.apply_weight = types.MethodType(mk("bold"), w.editor)
    w.editor.apply_italic = types.MethodType(mk("italic"), w.editor)
    w.editor.apply_strikethrough = types.MethodType(mk("strike"), w.editor)
    w.editor.apply_code = types.MethodType(mk("code"), w.editor)
    w.editor.apply_heading = types.MethodType(mk("heading"), w.editor)
    w.editor.toggle_bullets = types.MethodType(mk("bullets"), w.editor)
    w.editor.toggle_numbers = types.MethodType(mk("numbers"), w.editor)
    w.editor.toggle_checkboxes = types.MethodType(mk("checkboxes"), w.editor)

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
    calls2 = {"bold": 0}
    w.editor.apply_weight = types.MethodType(
        lambda self: calls2.__setitem__("bold", calls2["bold"] + 1), w.editor
    )

    tb.boldRequested.emit()
    assert calls1["bold"] == 1
    assert calls2["bold"] == 1

    w._open_date_in_tab(date2.addDays(-1))  # back to first tab
    tb.boldRequested.emit()
    assert calls1["bold"] == 2
    assert calls2["bold"] == 1


def test_history_and_insert_image_not_duplicated(
    qtbot, app, tmp_db_cfg, fresh_db, monkeypatch, tmp_path
):
    s = get_settings()
    s.setValue("db/default_db", str(tmp_db_cfg.path))
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

    def fake_insert(self, p):
        inserted["count"] += 1

    w.editor.insert_image_from_path = types.MethodType(fake_insert, w.editor)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *a, **k: ([str(dummy)], "Images (*.png)"),
        raising=False,
    )
    w.toolBar.insertImageRequested.emit()
    assert inserted["count"] == 1


def test_highlighter_attached_after_text_load(qtbot, app, tmp_db_cfg, fresh_db):
    s = get_settings()
    s.setValue("db/default_db", str(tmp_db_cfg.path))
    s.setValue("db/key", tmp_db_cfg.key)

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    w.editor.from_markdown("**bold**\n- [ ] task\n~~strike~~")
    assert w.editor.highlighter is not None
    assert w.editor.highlighter.document() is w.editor.document()


def test_findbar_works_for_current_tab(qtbot, app, tmp_db_cfg, fresh_db):
    s = get_settings()
    s.setValue("db/default_db", str(tmp_db_cfg.path))
    s.setValue("db/key", tmp_db_cfg.key)

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    # Tab 1 content
    w.editor.from_markdown("alpha bravo charlie")
    w.findBar.show_bar()
    w.findBar.edit.setText("bravo")
    w.findBar.find_next()
    assert w.editor.textCursor().selectedText() == "bravo"

    # Tab 2 content (contains the query too)
    date2 = w.calendar.selectedDate().addDays(1)
    w._open_date_in_tab(date2)
    w.editor.from_markdown("x bravo y bravo z")
    w.editor.moveCursor(QTextCursor.Start)
    w.findBar.find_next()
    assert w.editor.textCursor().selectedText() == "bravo"
