from bouquin.toolbar import ToolBar


def test_style_letter_button_handles_missing_widget(qtbot):
    tb = ToolBar()
    qtbot.addWidget(tb)
    # Create a dummy action detached from toolbar to force widgetForAction->None
    from PySide6.QtGui import QAction

    act = QAction("X", tb)
    # No crash and early return
    tb._style_letter_button(act, "X")


def test_style_letter_button_sets_tooltip_and_accessible(qtbot):
    tb = ToolBar()
    qtbot.addWidget(tb)
    # Use an existing action so widgetForAction returns a button
    act = tb.actBold
    tb._style_letter_button(act, "B", bold=True, tooltip="Bold")
    btn = tb.widgetForAction(act)
    assert btn.toolTip() == "Bold"
    assert btn.accessibleName() == "Bold"
