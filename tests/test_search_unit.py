from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

# The widget class is named `Search` in bouquin.search
from bouquin.search import Search as SearchWidget


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def search_entries(self, q):
        return list(self.rows)


def test_search_empty_clears_and_hides(qtbot):
    w = SearchWidget(db=FakeDB([]))
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    dates = []
    w.resultDatesChanged.connect(lambda ds: dates.extend(ds))
    w._search("   ")
    assert w.results.isHidden()
    assert dates == []


def test_populate_empty_hides(qtbot):
    w = SearchWidget(db=FakeDB([]))
    qtbot.addWidget(w)
    w._populate_results("x", [])
    assert w.results.isHidden()


def test_open_selected_emits_when_present(qtbot):
    w = SearchWidget(db=FakeDB([]))
    qtbot.addWidget(w)
    got = {}
    w.openDateRequested.connect(lambda d: got.setdefault("d", d))
    it = QListWidgetItem("x")
    it.setData(Qt.ItemDataRole.UserRole, "")
    w._open_selected(it)
    assert "d" not in got
    it.setData(Qt.ItemDataRole.UserRole, "2025-01-02")
    w._open_selected(it)
    assert got["d"] == "2025-01-02"


def test_make_html_snippet_edge_cases(qtbot):
    w = SearchWidget(db=FakeDB([]))
    qtbot.addWidget(w)
    # Empty HTML -> empty fragment, no ellipses
    frag, l, r = w._make_html_snippet("", "hello")
    assert frag == "" and not l and not r
    # Small doc around token -> should not show ellipses
    frag, l, r = w._make_html_snippet("<p>Hello world</p>", "world")
    assert "<b>world</b>" in frag or "world" in frag
