from bouquin.search import Search as SearchWidget


class DummyDB:
    def search_entries(self, q):
        return []


def test_make_html_snippet_no_match_triggers_start_window(qtbot):
    w = SearchWidget(db=DummyDB())
    qtbot.addWidget(w)
    html = "<p>" + ("x" * 300) + "</p>"  # long text, no token present
    frag, left, right = w._make_html_snippet(html, "notfound", radius=10, maxlen=80)
    assert frag != ""
    assert left is False and right is True
