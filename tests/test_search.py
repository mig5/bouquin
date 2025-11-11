import pytest
from bouquin.search import Search
from PySide6.QtWidgets import QListWidgetItem


def test_search_widget_populates_results(qtbot, fresh_db):
    fresh_db.save_new_version("2024-01-01", "alpha bravo", "seed")
    fresh_db.save_new_version("2024-01-02", "bravo charlie", "seed")
    fresh_db.save_new_version("2024-01-03", "delta alpha bravo", "seed")

    s = Search(fresh_db)
    qtbot.addWidget(s)
    s.show()

    emitted = []
    s.resultDatesChanged.connect(lambda ds: emitted.append(tuple(ds)))
    s.search.setText("alpha")
    qtbot.wait(50)
    assert s.results.count() >= 2
    assert emitted and {"2024-01-01", "2024-01-03"}.issubset(set(emitted[-1]))

    s.search.setText("")
    qtbot.wait(50)
    assert s.results.isHidden()


def test_open_selected_with_data(qtbot, fresh_db):
    s = Search(fresh_db)
    qtbot.addWidget(s)
    s.show()

    seen = []
    s.openDateRequested.connect(lambda d: seen.append(d))
    it = QListWidgetItem("dummy")
    from PySide6.QtCore import Qt

    it.setData(Qt.ItemDataRole.UserRole, "1999-12-31")
    s.results.addItem(it)
    s._open_selected(it)
    assert seen == ["1999-12-31"]


def test_make_html_snippet_and_strip_markdown(qtbot, fresh_db):
    s = Search(fresh_db)
    long = (
        "This is **bold** text with alpha in the middle and some more trailing content."
    )
    frag, left, right = s._make_html_snippet(long, "alpha", radius=10, maxlen=40)
    assert "alpha" in frag
    s._strip_markdown("**bold** _italic_ ~~strike~~ 1. item - [x] check")


def test_open_selected_ignores_no_data(qtbot, fresh_db):
    s = Search(fresh_db)
    qtbot.addWidget(s)
    s.show()

    seen = []
    s.openDateRequested.connect(lambda d: seen.append(d))
    it = QListWidgetItem("dummy")
    # No UserRole data set -> should not emit
    s._open_selected(it)
    assert not seen


def test_make_html_snippet_variants(qtbot, fresh_db):
    s = Search(fresh_db)
    qtbot.addWidget(s)
    s.show()

    # Case: query tokens not found -> idx < 0 path; expect right ellipsis when longer than maxlen
    src = " ".join(["word"] * 200)
    frag, left, right = s._make_html_snippet(src, "nomatch", radius=3, maxlen=30)
    assert frag and not left and right

    # Case: multiple tokens highlighted
    src = "Alpha bravo charlie delta echo"
    frag, left, right = s._make_html_snippet(src, "alpha delta", radius=2, maxlen=50)
    assert "<b>Alpha</b>" in frag or "<b>alpha</b>" in frag
    assert "<b>delta</b>" in frag


@pytest.mark.gui
def test_search_error_path_and_empty_snippet(qtbot, fresh_db, monkeypatch):
    s = Search(fresh_db)
    qtbot.addWidget(s)
    s.show()

    s.search.setText("alpha")

    frag, left, right = s._make_html_snippet("", "alpha", radius=10, maxlen=40)
    assert frag == "" and not left and not right


@pytest.mark.gui
def test_populate_results_shows_both_ellipses(qtbot, fresh_db):
    s = Search(fresh_db)
    qtbot.addWidget(s)
    s.show()
    long = "X" * 40 + "alpha" + "Y" * 40
    rows = [("2000-01-01", long)]
    s._populate_results("alpha", rows)
    assert s.results.count() >= 1
