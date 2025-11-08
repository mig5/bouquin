import pytest

from PySide6.QtGui import QImage, QColor
from bouquin.markdown_editor import MarkdownEditor
from bouquin.theme import ThemeManager, ThemeConfig, Theme


@pytest.fixture
def editor(app, qtbot):
    themes = ThemeManager(app, ThemeConfig(theme=Theme.LIGHT))
    ed = MarkdownEditor(themes)
    qtbot.addWidget(ed)
    ed.show()
    return ed


def test_from_and_to_markdown_roundtrip(editor):
    md = "# Title\n\nThis is **bold** and _italic_ and ~~strike~~.\n\n- [ ] task\n- [x] done\n\n```\ncode\n```"
    editor.from_markdown(md)
    out = editor.to_markdown()
    assert "Title" in out and "task" in out and "code" in out


def test_apply_styles_and_headings(editor, qtbot):
    editor.from_markdown("hello world")
    editor.selectAll()
    editor.apply_weight()
    editor.apply_italic()
    editor.apply_strikethrough()
    editor.apply_heading(24)
    md = editor.to_markdown()
    assert "**" in md and "*~~~~*" in md


def test_toggle_lists_and_checkboxes(editor):
    editor.from_markdown("item one\nitem two\n")
    editor.toggle_bullets()
    assert "- " in editor.to_markdown()
    editor.toggle_numbers()
    assert "1. " in editor.to_markdown()
    editor.toggle_checkboxes()
    md = editor.to_markdown()
    assert "- [ ]" in md or "- [x]" in md


def test_insert_image_from_path(editor, tmp_path):
    img = tmp_path / "pic.png"
    qimg = QImage(2, 2, QImage.Format_RGBA8888)
    qimg.fill(QColor(255, 0, 0))
    assert qimg.save(str(img))  # ensure a valid PNG on disk

    editor.insert_image_from_path(img)
    md = editor.to_markdown()
    # Images are saved as base64 data URIs in markdown
    assert "data:image/image/png;base64" in md


def test_apply_code_inline(editor):
    editor.from_markdown("alpha beta")
    editor.selectAll()
    editor.apply_code()
    md = editor.to_markdown()
    assert ("`" in md) or ("```" in md)
