from bouquin.search import Search


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
