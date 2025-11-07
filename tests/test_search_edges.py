import os
import tempfile
from PySide6.QtWidgets import QApplication
import pytest

from bouquin.db import DBConfig, DBManager
from bouquin.search import Search

@pytest.fixture(scope="module")
def app():
    # Ensure a single QApplication exists
    a = QApplication.instance()
    if a is None:
        a = QApplication([])
    yield a

@pytest.fixture
def fresh_db(tmp_path):
    cfg = DBConfig(path=tmp_path / "test.db", key="testkey")
    db = DBManager(cfg)
    assert db.connect() is True
    # Seed a couple of entries
    db.save_new_version("2025-01-01", "<p>Hello world first day</p>")
    db.save_new_version("2025-01-02", "<p>Lorem ipsum dolor sit amet, consectetur adipiscing elit.</p>")
    db.save_new_version("2025-01-03", "<p>Long content begins " + ("x"*200) + " middle token here " + ("y"*200) + " ends.</p>")
    return db

def test_search_exception_path_closed_db_triggers_quiet_handling(app, fresh_db, qtbot):
    # Close the DB to provoke an exception inside Search._search
    fresh_db.close()
    w = Search(fresh_db)
    w.show()
    qtbot.addWidget(w)

    # Typing should not raise; exception path returns empty results
    w._search("anything")
    assert w.results.isHidden()  # remains hidden because there are no rows
    # Also, the "resultDatesChanged" signal should emit an empty list (coverage on that branch)

def test_make_html_snippet_ellipses_both_sides(app, fresh_db):
    w = Search(fresh_db)
    # Choose a query so that the first match sits well inside a long string,
    # forcing both left and right ellipses.
    html = fresh_db.get_entry("2025-01-03")
    snippet, left_ell, right_ell = w._make_html_snippet(html, "middle")
    assert snippet  # non-empty
    assert left_ell is True
    assert right_ell is True
