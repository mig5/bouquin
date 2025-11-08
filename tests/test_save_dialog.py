from bouquin.save_dialog import SaveDialog


def test_save_dialog_note_text(qtbot):
    dlg = SaveDialog()
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.note_text()
