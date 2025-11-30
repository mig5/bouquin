from PySide6.QtWidgets import QPushButton
from bouquin.code_block_editor_dialog import CodeBlockEditorDialog
from bouquin import strings


def _find_button_by_text(widget, text):
    for btn in widget.findChildren(QPushButton):
        if text.lower() in btn.text().lower():
            return btn
    return None


def test_code_block_dialog_delete_flow(qtbot):
    dlg = CodeBlockEditorDialog("print(1)", "python", allow_delete=True)
    qtbot.addWidget(dlg)
    delete_txt = strings._("delete_code_block")
    delete_btn = _find_button_by_text(dlg, delete_txt)
    assert delete_btn is not None
    assert not dlg.was_deleted()
    with qtbot.waitSignal(dlg.finished, timeout=2000):
        delete_btn.click()
    assert dlg.was_deleted()


def test_code_block_dialog_language_and_code(qtbot):
    dlg = CodeBlockEditorDialog("x = 1", "not-a-lang", allow_delete=False)
    qtbot.addWidget(dlg)
    delete_txt = strings._("delete_code_block")
    assert _find_button_by_text(dlg, delete_txt) is None
    assert dlg.code() == "x = 1"
    assert dlg.language() is None
