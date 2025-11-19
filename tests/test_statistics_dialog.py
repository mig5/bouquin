import datetime as _dt

from bouquin import strings

from datetime import date
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QLabel
from PySide6.QtTest import QTest

from bouquin.statistics_dialog import DateHeatmap, StatisticsDialog


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


def _date(year, month, day):
    return date(year, month, day)


# ============================================================================
# DateHeatmapTests - Missing Coverage
# ============================================================================


def test_activity_heatmap_empty_data(qtbot):
    """Test heatmap with empty data dict."""
    strings.load_strings("en")
    heatmap = DateHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.show()

    # Set empty data
    heatmap.set_data({})

    # Should handle empty data gracefully
    assert heatmap._start is None
    assert heatmap._end is None
    assert heatmap._max_value == 0

    # Size hint should return default dimensions
    size = heatmap.sizeHint()
    assert size.width() > 0
    assert size.height() > 0

    # Paint should not crash
    heatmap.update()
    qtbot.wait(10)


def test_activity_heatmap_none_data(qtbot):
    """Test heatmap with None data."""
    strings.load_strings("en")
    heatmap = DateHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.show()

    # Set None data
    heatmap.set_data(None)

    assert heatmap._start is None
    assert heatmap._end is None

    # Paint event should return early
    heatmap.update()
    qtbot.wait(10)


def test_activity_heatmap_click_when_no_data(qtbot):
    """Test clicking heatmap when there's no data."""
    heatmap = DateHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.show()

    heatmap.set_data({})

    # Simulate click - should not crash or emit signal
    clicked_dates = []
    heatmap.date_clicked.connect(clicked_dates.append)

    # Click in the middle of widget
    pos = QPoint(100, 100)
    QTest.mouseClick(heatmap, Qt.LeftButton, pos=pos)

    # Should not have clicked any date
    assert len(clicked_dates) == 0


def test_activity_heatmap_click_outside_grid(qtbot):
    """Test clicking outside the grid area."""
    heatmap = DateHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.show()

    # Set some data
    data = {
        date(2024, 1, 1): 5,
        date(2024, 1, 2): 10,
    }
    heatmap.set_data(data)

    clicked_dates = []
    heatmap.date_clicked.connect(clicked_dates.append)

    # Click in top-left margin (before grid starts)
    pos = QPoint(5, 5)
    QTest.mouseClick(heatmap, Qt.LeftButton, pos=pos)

    assert len(clicked_dates) == 0


def test_activity_heatmap_click_beyond_end_date(qtbot):
    """Test clicking on trailing empty cells beyond the last date."""
    heatmap = DateHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.show()

    # Set data that doesn't fill a complete week
    data = {
        date(2024, 1, 1): 5,  # Monday
        date(2024, 1, 2): 10,  # Tuesday
    }
    heatmap.set_data(data)

    clicked_dates = []
    heatmap.date_clicked.connect(clicked_dates.append)

    # Try clicking far to the right (beyond end date)
    # This is tricky to target precisely, but we can simulate
    pos = QPoint(1000, 50)  # Far right
    QTest.mouseClick(heatmap, Qt.LeftButton, pos=pos)

    # Should either not click or only click valid dates
    # If it did click, it should be a valid date within range
    if clicked_dates:
        assert clicked_dates[0] <= date(2024, 1, 2)


def test_activity_heatmap_click_invalid_row(qtbot):
    """Test clicking below the 7 weekday rows."""
    heatmap = DateHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.show()

    data = {
        date(2024, 1, 1): 5,
        date(2024, 1, 8): 10,
    }
    heatmap.set_data(data)

    clicked_dates = []
    heatmap.date_clicked.connect(clicked_dates.append)

    # Click below the grid (row 8 or higher)
    pos = QPoint(100, 500)  # Very low Y
    QTest.mouseClick(heatmap, Qt.LeftButton, pos=pos)

    assert len(clicked_dates) == 0


def test_activity_heatmap_right_click_ignored(qtbot):
    """Test that right-click is ignored."""
    heatmap = DateHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.show()

    data = {date(2024, 1, 1): 5}
    heatmap.set_data(data)

    clicked_dates = []
    heatmap.date_clicked.connect(clicked_dates.append)

    # Right click should be ignored
    pos = QPoint(100, 100)
    QTest.mouseClick(heatmap, Qt.RightButton, pos=pos)

    assert len(clicked_dates) == 0


def test_activity_heatmap_month_label_rendering(qtbot):
    """Test heatmap spanning multiple months renders month labels."""
    heatmap = DateHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.show()

    # Data spanning multiple months
    data = {
        date(2024, 1, 1): 5,
        date(2024, 1, 15): 10,
        date(2024, 2, 1): 8,
        date(2024, 2, 15): 12,
        date(2024, 3, 1): 6,
    }
    heatmap.set_data(data)

    # Should calculate proper size
    size = heatmap.sizeHint()
    assert size.width() > 0
    assert size.height() > 0

    # Paint should work without crashing
    heatmap.update()
    qtbot.wait(10)


def test_activity_heatmap_same_month_continues(qtbot):
    """Test that month labels skip weeks in the same month."""
    heatmap = DateHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.show()

    # Multiple dates in same month
    data = {}
    for day in range(1, 29):  # January 1-28
        data[date(2024, 1, day)] = day

    heatmap.set_data(data)

    # Should render without issues
    heatmap.update()
    qtbot.wait(10)


def test_activity_heatmap_data_with_zero_values(qtbot):
    """Test heatmap with zero values in data."""
    heatmap = DateHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.show()

    data = {
        date(2024, 1, 1): 0,
        date(2024, 1, 2): 5,
        date(2024, 1, 3): 0,
    }
    heatmap.set_data(data)

    assert heatmap._max_value == 5

    heatmap.update()
    qtbot.wait(10)


def test_activity_heatmap_single_day(qtbot):
    """Test heatmap with just one day of data."""
    heatmap = DateHeatmap()
    qtbot.addWidget(heatmap)
    heatmap.show()

    data = {date(2024, 1, 15): 10}
    heatmap.set_data(data)

    # Should handle single day
    assert heatmap._start is not None
    assert heatmap._end is not None

    clicked_dates = []
    heatmap.date_clicked.connect(clicked_dates.append)

    # Click should work
    pos = QPoint(100, 100)
    QTest.mouseClick(heatmap, Qt.LeftButton, pos=pos)


# ============================================================================
# StatisticsDialog Tests
# ============================================================================


def test_statistics_dialog_with_empty_database(qtbot, fresh_db):
    """Test statistics dialog with an empty database."""
    strings.load_strings("en")

    dialog = StatisticsDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.show()

    # Should handle empty database gracefully
    assert dialog.isVisible()

    # Heatmap should be empty
    heatmap = dialog.findChild(DateHeatmap)
    if heatmap:
        # No crash when displaying empty heatmap
        qtbot.wait(10)


def test_statistics_dialog_with_data(qtbot, fresh_db):
    """Test statistics dialog with actual data."""
    strings.load_strings("en")

    # Add some content
    fresh_db.save_new_version("2024-01-01", "Hello world", "test")
    fresh_db.save_new_version("2024-01-02", "More content here", "test")
    fresh_db.save_new_version("2024-01-03", "Even more text", "test")

    dialog = StatisticsDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.show()

    # Should display statistics
    assert dialog.isVisible()
    qtbot.wait(10)


def test_statistics_dialog_gather_stats_exception_handling(
    qtbot, fresh_db, monkeypatch
):
    """Test that gather_stats handles exceptions gracefully."""
    strings.load_strings("en")

    # Make dates_with_content raise an exception
    def bad_dates_with_content():
        raise RuntimeError("Simulated DB error")

    monkeypatch.setattr(fresh_db, "dates_with_content", bad_dates_with_content)

    # Should still create dialog without crashing
    dialog = StatisticsDialog(fresh_db)
    qtbot.addWidget(dialog)
    dialog.show()

    # Should handle error gracefully
    assert dialog.isVisible()
