import pytest
from PySide6.QtCore import QDate

from bouquin.main_window import MainWindow
from bouquin.theme import Theme, ThemeConfig, ThemeManager
from bouquin.settings import get_settings
from bouquin.key_prompt import KeyPrompt
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


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
    from PySide6.QtCore import QDate
    from bouquin.theme import ThemeManager, ThemeConfig, Theme
    from bouquin.settings import get_settings

    s = get_settings()
    s.setValue("db/path", str(tmp_db_cfg.path))
    s.setValue("db/key", tmp_db_cfg.key)
    s.setValue("ui/move_todos", True)
    s.setValue("ui/theme", "light")

    y = QDate.currentDate().addDays(-1).toString("yyyy-MM-dd")
    fresh_db.save_new_version(y, "- [ ] carry me\n- [x] done", "seed")

    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    from bouquin.main_window import MainWindow

    w = MainWindow(themes=themes)
    qtbot.addWidget(w)
    w.show()

    w._load_yesterday_todos()

    assert "carry me" in w.editor.to_markdown()
    y_txt = fresh_db.get_entry(y)
    assert "carry me" not in y_txt or "- [ ]" not in y_txt
