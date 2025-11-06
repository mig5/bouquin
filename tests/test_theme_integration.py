from bouquin.theme import Theme


def test_apply_link_css_dark_theme(open_window, qtbot):
    win = open_window
    # Switch to dark and apply link CSS
    win.themes.set(Theme.DARK)
    win._apply_link_css()
    css = win.editor.document().defaultStyleSheet()
    assert "#FFA500" in css and "a:visited" in css


def test_apply_link_css_light_theme(open_window, qtbot):
    win = open_window
    # Switch to light and apply link CSS
    win.themes.set(Theme.LIGHT)
    win._apply_link_css()
    css = win.editor.document().defaultStyleSheet()
    assert css == "" or "a {" not in css
