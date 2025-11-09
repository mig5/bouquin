import pytest
from PySide6.QtWidgets import QWidget
from bouquin.markdown_editor import MarkdownEditor
from bouquin.theme import ThemeManager, ThemeConfig, Theme
from bouquin.toolbar import ToolBar


@pytest.fixture
def editor(app, qtbot):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    ed = MarkdownEditor(themes)
    qtbot.addWidget(ed)
    ed.show()
    return ed

@pytest.mark.gui
def test_toolbar_signals_and_styling(qtbot, editor):
    host = QWidget()
    qtbot.addWidget(host)
    host.show()

    tb = ToolBar(parent=host)
    qtbot.addWidget(tb)
    tb.show()

    tb.boldRequested.connect(editor.apply_weight)
    tb.italicRequested.connect(editor.apply_italic)
    tb.strikeRequested.connect(editor.apply_strikethrough)
    tb.codeRequested.connect(lambda: editor.apply_code())
    tb.headingRequested.connect(lambda s: editor.apply_heading(s))
    tb.bulletsRequested.connect(lambda: editor.toggle_bullets())
    tb.numbersRequested.connect(lambda: editor.toggle_numbers())
    tb.checkboxesRequested.connect(lambda: editor.toggle_checkboxes())

    editor.from_markdown("hello")
    editor.selectAll()
    tb.boldRequested.emit()
    tb.italicRequested.emit()
    tb.strikeRequested.emit()
    tb.headingRequested.emit(24)
    assert editor.to_markdown()
