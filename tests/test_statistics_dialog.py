import datetime as _dt

from PySide6.QtWidgets import QLabel

from bouquin.statistics_dialog import StatisticsDialog
from bouquin import strings


class FakeStatsDB:
    """Minimal stub that returns a fixed stats payload."""

    def __init__(self):
        d1 = _dt.date(2024, 1, 1)
        d2 = _dt.date(2024, 1, 2)
        self.stats = (
            2,  # pages_with_content
            5,  # total_revisions
            "2024-01-02",  # page_most_revisions
            3,  # page_most_revisions_count
            {d1: 10, d2: 20},  # words_by_date
            30,  # total_words
            4,  # unique_tags
            "2024-01-02",  # page_most_tags
            2,  # page_most_tags_count
            {d1: 1, d2: 2},  # revisions_by_date
        )
        self.called = False

    def gather_stats(self):
        self.called = True
        return self.stats


def test_statistics_dialog_populates_fields_and_heatmap(qtbot):
    # Make sure we have a known language for label texts
    strings.load_strings("en")

    db = FakeStatsDB()
    dlg = StatisticsDialog(db)
    qtbot.addWidget(dlg)
    dlg.show()

    # Stats were actually requested from the DB
    assert db.called

    # Window title comes from translations
    assert dlg.windowTitle() == strings._("statistics")

    # Grab all label texts for simple content checks
    label_texts = {lbl.text() for lbl in dlg.findChildren(QLabel)}

    # Page with most revisions / tags are rendered as "DATE (COUNT)"
    assert "2024-01-02 (3)" in label_texts
    assert "2024-01-02 (2)" in label_texts

    # Heatmap is created and uses "words" by default
    words_by_date = db.stats[4]
    revisions_by_date = db.stats[-1]

    assert hasattr(dlg, "_heatmap")
    assert dlg._heatmap._data == words_by_date

    # Switching the metric to "revisions" should swap the dataset
    dlg.metric_combo.setCurrentIndex(1)  # 0 = words, 1 = revisions
    qtbot.wait(10)
    assert dlg._heatmap._data == revisions_by_date


class EmptyStatsDB:
    """Stub that returns a 'no data yet' stats payload."""

    def __init__(self):
        self.called = False

    def gather_stats(self):
        self.called = True
        return (
            0,  # pages_with_content
            0,  # total_revisions
            None,  # page_most_revisions
            0,
            {},  # words_by_date
            0,  # total_words
            0,  # unique_tags
            None,  # page_most_tags
            0,
            {},  # revisions_by_date
        )


def test_statistics_dialog_no_data_shows_placeholder(qtbot):
    strings.load_strings("en")

    db = EmptyStatsDB()
    dlg = StatisticsDialog(db)
    qtbot.addWidget(dlg)
    dlg.show()

    assert db.called

    label_texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    assert strings._("stats_no_data") in label_texts

    # When there's no data, the heatmap and metric combo shouldn't exist
    assert not hasattr(dlg, "metric_combo")
    assert not hasattr(dlg, "_heatmap")
