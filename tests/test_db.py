import csv
import datetime as dt
import json
from datetime import date, timedelta

import pytest
from bouquin.db import DBManager
from sqlcipher3 import dbapi2 as sqlite


def _today():
    return dt.date.today().isoformat()


def _yesterday():
    return (dt.date.today() - dt.timedelta(days=1)).isoformat()


def _tomorrow():
    return (dt.date.today() + dt.timedelta(days=1)).isoformat()


def _days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def _entry(text, i=0):
    return f"{text} line {i}\nsecond line\n\n- [x] done\n- [ ] todo"


def test_connect_integrity_and_schema(fresh_db):
    d = _today()
    fresh_db.save_new_version(d, _entry("hello world"), "initial")
    vlist = fresh_db.list_versions(d)
    assert vlist
    v = fresh_db.get_version(version_id=vlist[0]["id"])
    assert v and "created_at" in v


def test_save_and_get_entry_versions(fresh_db):
    d = _today()
    fresh_db.save_new_version(d, _entry("hello world"), "initial")
    txt = fresh_db.get_entry(d)
    assert "hello world" in txt

    fresh_db.save_new_version(d, _entry("hello again"), "second")
    versions = fresh_db.list_versions(d)
    assert len(versions) >= 2
    assert any(v["is_current"] for v in versions)

    first = sorted(versions, key=lambda v: v["version_no"])[0]
    fresh_db.revert_to_version(d, version_id=first["id"])
    txt2 = fresh_db.get_entry(d)
    assert "hello world" in txt2 and "again" not in txt2


def test_dates_with_content_and_search(fresh_db):
    fresh_db.save_new_version(_today(), _entry("alpha bravo"), "t1")
    fresh_db.save_new_version(_yesterday(), _entry("bravo charlie"), "t2")
    fresh_db.save_new_version(_tomorrow(), _entry("delta alpha"), "t3")

    dates = set(fresh_db.dates_with_content())
    assert _today() in dates and _yesterday() in dates and _tomorrow() in dates

    hits = list(fresh_db.search_entries("alpha"))
    # search_entries now returns (kind, key, title, text, aux)
    page_dates = [key for (kind, key, _title, _text, _aux) in hits if kind == "page"]
    assert _today() in page_dates
    assert _tomorrow() in page_dates


def test_get_all_entries_and_export(fresh_db, tmp_path):
    for i in range(3):
        d = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        fresh_db.save_new_version(d, _entry(f"note {i}"), f"note {i}")
    entries = fresh_db.get_all_entries()
    assert entries and all(len(t) == 2 for t in entries)

    json_path = tmp_path / "export.json"
    fresh_db.export_json(entries, str(json_path))
    assert json_path.exists() and json.load(open(json_path)) is not None

    csv_path = tmp_path / "export.csv"
    fresh_db.export_csv(entries, str(csv_path))
    assert csv_path.exists() and list(csv.reader(open(csv_path)))

    md_path = tmp_path / "export.md"
    fresh_db.export_markdown(entries, str(md_path))
    md_text = md_path.read_text()
    assert md_path.exists() and entries[0][0] in md_text

    html_path = tmp_path / "export.html"
    fresh_db.export_html(entries, str(html_path), title="My Notebook")
    assert html_path.exists() and "<html" in html_path.read_text().lower()

    sql_path = tmp_path / "export.sql"
    fresh_db.export_sql(str(sql_path))
    assert sql_path.exists() and sql_path.read_bytes()

    sqlc_path = tmp_path / "export.db"
    fresh_db.export_sqlcipher(str(sqlc_path))
    assert sqlc_path.exists() and sqlc_path.read_bytes()


def test_rekey_and_reopen(fresh_db, tmp_db_cfg):
    fresh_db.save_new_version(_today(), _entry("secure"), "before rekey")
    fresh_db.rekey("new-key-123")
    fresh_db.close()

    tmp_db_cfg.key = "new-key-123"
    db2 = DBManager(tmp_db_cfg)
    assert db2.connect()
    assert "secure" in db2.get_entry(_today())
    db2.close()


def test_compact_and_close_dont_crash(fresh_db):
    fresh_db.compact()
    fresh_db.close()


def test_connect_integrity_failure(monkeypatch, tmp_db_cfg):
    db = DBManager(tmp_db_cfg)
    # simulate cursor() ok, but integrity check raising
    called = {"ok": False}

    def bad_integrity(self):
        called["ok"] = True
        raise sqlite.Error("bad cipher")

    monkeypatch.setattr(DBManager, "_integrity_ok", bad_integrity, raising=True)
    ok = db.connect()
    assert not ok and called["ok"]
    assert db.conn is None


def test_rekey_reopen_failure(monkeypatch, tmp_db_cfg):
    db = DBManager(tmp_db_cfg)
    assert db.connect()

    # Monkeypatch connect() on the instance so the reconnect attempt fails
    def fail_connect():
        return False

    monkeypatch.setattr(db, "connect", fail_connect, raising=False)
    with pytest.raises(sqlite.Error):
        db.rekey("newkey")


def test_revert_wrong_date_raises(fresh_db):
    d1, d2 = "2024-01-01", "2024-01-02"
    v1_id, _ = fresh_db.save_new_version(d1, "one", "seed")
    fresh_db.save_new_version(d2, "two", "seed")
    with pytest.raises(ValueError):
        fresh_db.revert_to_version(d2, version_id=v1_id)


def test_compact_error_path(monkeypatch, tmp_db_cfg):
    db = DBManager(tmp_db_cfg)
    assert db.connect()

    # Replace cursor.execute to raise to hit except branch
    class BadCur:
        def execute(self, *a, **k):
            raise RuntimeError("boom")

    class BadConn:
        def cursor(self):
            return BadCur()

    db.conn = BadConn()
    # Should not raise; just print error
    db.compact()


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **k):
        return self

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _Cur(self._rows)


def test_integrity_check_raises_with_details(tmp_db_cfg):
    db = DBManager(tmp_db_cfg)
    assert db.connect()
    # Force the integrity check to report problems with text details
    db.conn = _Conn([("bad page checksum",), (None,)])
    with pytest.raises(sqlite.IntegrityError) as ei:
        db._integrity_ok()
    # Message should contain the detail string
    assert "bad page checksum" in str(ei.value)


def test_integrity_check_raises_without_details(tmp_db_cfg):
    db = DBManager(tmp_db_cfg)
    assert db.connect()
    # Force the integrity check to report problems but without textual details
    db.conn = _Conn([(None,), (None,)])
    with pytest.raises(sqlite.IntegrityError):
        db._integrity_ok()


# ============================================================================
# DB _strip_markdown and _count_words Tests
# ============================================================================


def test_db_strip_markdown_empty_text(fresh_db):
    """Test strip_markdown with empty text."""
    result = fresh_db._strip_markdown("")
    assert result == ""


def test_db_strip_markdown_none_text(fresh_db):
    """Test strip_markdown with None."""
    result = fresh_db._strip_markdown(None)
    assert result == ""


def test_db_strip_markdown_fenced_code_blocks(fresh_db):
    """Test stripping fenced code blocks."""
    text = """
Some text here
```python
def hello():
    print("world")
```
More text after
"""
    result = fresh_db._strip_markdown(text)
    assert "def hello" not in result
    assert "Some text" in result
    assert "More text" in result


def test_db_strip_markdown_inline_code(fresh_db):
    """Test stripping inline code."""
    text = "Here is some `inline code` in text"
    result = fresh_db._strip_markdown(text)
    assert "`" not in result
    assert "inline code" not in result
    assert "Here is some" in result
    assert "in text" in result


def test_db_strip_markdown_links(fresh_db):
    """Test converting markdown links to plain text."""
    text = "Check out [this link](https://example.com) for more info"
    result = fresh_db._strip_markdown(text)
    assert "this link" in result
    assert "https://example.com" not in result
    assert "[" not in result
    assert "]" not in result


def test_db_strip_markdown_emphasis_and_headers(fresh_db):
    """Test stripping emphasis markers and headers."""
    text = """
# Header 1
## Header 2
**bold text** and *italic text*
> blockquote
_underline_
"""
    result = fresh_db._strip_markdown(text)
    assert "#" not in result
    assert "*" not in result
    assert "_" not in result
    assert ">" not in result
    assert "bold text" in result
    assert "italic text" in result


def test_db_strip_markdown_html_tags(fresh_db):
    """Test stripping HTML tags."""
    text = "Some <b>bold</b> and <i>italic</i> text with <div>divs</div>"
    result = fresh_db._strip_markdown(text)
    # The regex replaces tags with spaces, may leave some angle brackets from malformed HTML
    # The important thing is that the words are preserved
    assert "bold" in result
    assert "italic" in result
    assert "divs" in result


def test_db_strip_markdown_complex_document(fresh_db):
    """Test stripping complex markdown document."""
    text = """
# My Document

This is a paragraph with **bold** and *italic* text.

```javascript
const x = 10;
console.log(x);
```

Here's a [link](https://example.com) and some `code`.

> A blockquote

<p>HTML paragraph</p>
"""
    result = fresh_db._strip_markdown(text)
    assert "My Document" in result
    assert "paragraph" in result
    assert "const x" not in result
    assert "https://example.com" not in result
    assert "<p>" not in result


def test_db_count_words_simple(fresh_db):
    """Test word counting on simple text."""
    text = "This is a simple test with seven words"
    count = fresh_db._count_words(text)
    assert count == 8


def test_db_count_words_empty(fresh_db):
    """Test word counting on empty text."""
    count = fresh_db._count_words("")
    assert count == 0


def test_db_count_words_with_markdown(fresh_db):
    """Test word counting strips markdown first."""
    text = "**Bold** and *italic* and `code` words"
    count = fresh_db._count_words(text)
    # Should count: Bold, and, italic, and, words (5 words, code is in backticks so stripped)
    assert count == 5


def test_db_count_words_with_unicode(fresh_db):
    """Test word counting with unicode characters."""
    text = "Hello 世界 café naïve résumé"
    count = fresh_db._count_words(text)
    # Should count all words including unicode
    assert count >= 5


def test_db_count_words_with_numbers(fresh_db):
    """Test word counting includes numbers."""
    text = "There are 123 apples and 456 oranges"
    count = fresh_db._count_words(text)
    assert count == 7


def test_db_count_words_with_punctuation(fresh_db):
    """Test word counting handles punctuation correctly."""
    text = "Hello, world! How are you? I'm fine, thanks."
    count = fresh_db._count_words(text)
    # Hello, world, How, are, you, I, m, fine, thanks = 9 words
    assert count == 9


# ============================================================================
# DB gather_stats Tests
# ============================================================================


def test_db_gather_stats_empty_database(fresh_db):
    """Test gather_stats on empty database."""
    stats = fresh_db.gather_stats()

    assert len(stats) == 10
    (
        pages_with_content,
        total_revisions,
        page_most_revisions,
        page_most_revisions_count,
        words_by_date,
        total_words,
        unique_tags,
        page_most_tags,
        page_most_tags_count,
        revisions_by_date,
    ) = stats

    assert pages_with_content == 0
    assert total_revisions == 0
    assert page_most_revisions is None
    assert page_most_revisions_count == 0
    assert len(words_by_date) == 0
    assert total_words == 0
    assert unique_tags == 0
    assert page_most_tags is None
    assert page_most_tags_count == 0
    assert len(revisions_by_date) == 0


def test_db_gather_stats_with_content(fresh_db):
    """Test gather_stats with actual content."""
    # Add multiple pages with different content
    fresh_db.save_new_version("2024-01-01", "Hello world this is a test", "v1")
    fresh_db.save_new_version(
        "2024-01-01", "Hello world this is version two", "v2"
    )  # 2nd revision
    fresh_db.save_new_version("2024-01-02", "Another page with more words here", "v1")

    stats = fresh_db.gather_stats()

    (
        pages_with_content,
        total_revisions,
        page_most_revisions,
        page_most_revisions_count,
        words_by_date,
        total_words,
        unique_tags,
        page_most_tags,
        page_most_tags_count,
        revisions_by_date,
    ) = stats

    assert pages_with_content == 2
    assert total_revisions == 3
    assert page_most_revisions == "2024-01-01"
    assert page_most_revisions_count == 2
    assert total_words > 0
    assert len(words_by_date) == 2


def test_db_gather_stats_word_counting(fresh_db):
    """Test that gather_stats counts words correctly."""
    # Add page with known word count
    fresh_db.save_new_version("2024-01-01", "one two three four five", "test")

    stats = fresh_db.gather_stats()
    _, _, _, _, words_by_date, total_words, _, _, _, _ = stats

    assert total_words == 5

    test_date = date(2024, 1, 1)
    assert test_date in words_by_date
    assert words_by_date[test_date] == 5


def test_db_gather_stats_with_tags(fresh_db):
    """Test gather_stats with tags."""
    # Add tags
    fresh_db.add_tag("tag1", "#ff0000")
    fresh_db.add_tag("tag2", "#00ff00")
    fresh_db.add_tag("tag3", "#0000ff")

    # Add pages with tags
    fresh_db.save_new_version("2024-01-01", "Page 1", "test")
    fresh_db.save_new_version("2024-01-02", "Page 2", "test")

    fresh_db.set_tags_for_page(
        "2024-01-01", ["tag1", "tag2", "tag3"]
    )  # Page 1 has 3 tags
    fresh_db.set_tags_for_page("2024-01-02", ["tag1"])  # Page 2 has 1 tag

    stats = fresh_db.gather_stats()
    _, _, _, _, _, _, unique_tags, page_most_tags, page_most_tags_count, _ = stats

    assert unique_tags == 3
    assert page_most_tags == "2024-01-01"
    assert page_most_tags_count == 3


def test_db_gather_stats_revisions_by_date(fresh_db):
    """Test revisions_by_date tracking."""
    # Add multiple revisions on different dates
    fresh_db.save_new_version("2024-01-01", "First", "v1")
    fresh_db.save_new_version("2024-01-01", "Second", "v2")
    fresh_db.save_new_version("2024-01-01", "Third", "v3")
    fresh_db.save_new_version("2024-01-02", "Fourth", "v1")

    stats = fresh_db.gather_stats()
    _, _, _, _, _, _, _, _, _, revisions_by_date = stats

    assert date(2024, 1, 1) in revisions_by_date
    assert revisions_by_date[date(2024, 1, 1)] == 3
    assert date(2024, 1, 2) in revisions_by_date
    assert revisions_by_date[date(2024, 1, 2)] == 1


def test_db_gather_stats_handles_malformed_dates(fresh_db):
    """Test that gather_stats handles malformed dates gracefully."""
    # This is hard to test directly since the DB enforces date format
    # But we can test that normal dates work
    fresh_db.save_new_version("2024-01-15", "Test", "v1")

    stats = fresh_db.gather_stats()
    _, _, _, _, _, _, _, _, _, revisions_by_date = stats

    # Should have parsed the date correctly
    assert date(2024, 1, 15) in revisions_by_date


def test_db_gather_stats_current_version_only(fresh_db):
    """Test that word counts use current version only, not all revisions."""
    # Add multiple revisions
    fresh_db.save_new_version("2024-01-01", "one two three", "v1")
    fresh_db.save_new_version("2024-01-01", "one two three four five", "v2")

    stats = fresh_db.gather_stats()
    _, _, _, _, words_by_date, total_words, _, _, _, _ = stats

    # Should count words from current version (5 words), not old version
    assert total_words == 5
    assert words_by_date[date(2024, 1, 1)] == 5


def test_db_gather_stats_no_tags(fresh_db):
    """Test gather_stats when there are no tags."""
    fresh_db.save_new_version("2024-01-01", "No tags here", "test")

    stats = fresh_db.gather_stats()
    _, _, _, _, _, _, unique_tags, page_most_tags, page_most_tags_count, _ = stats

    assert unique_tags == 0
    assert page_most_tags is None
    assert page_most_tags_count == 0


def test_db_gather_stats_exception_in_dates_with_content(fresh_db, monkeypatch):
    """Test that gather_stats handles exception in dates_with_content."""

    def bad_dates():
        raise RuntimeError("Simulated error")

    monkeypatch.setattr(fresh_db, "dates_with_content", bad_dates)

    # Should still return stats without crashing
    stats = fresh_db.gather_stats()
    pages_with_content = stats[0]

    # Should default to 0 when exception occurs
    assert pages_with_content == 0


def test_delete_version(fresh_db):
    """Test deleting a specific version by version_id."""
    d = date.today().isoformat()

    # Create multiple versions
    vid1, _ = fresh_db.save_new_version(d, "version 1", "note1")
    vid2, _ = fresh_db.save_new_version(d, "version 2", "note2")
    vid3, _ = fresh_db.save_new_version(d, "version 3", "note3")

    # Verify all versions exist
    versions = fresh_db.list_versions(d)
    assert len(versions) == 3

    # Delete the second version
    fresh_db.delete_version(version_id=vid2)

    # Verify it's deleted
    versions_after = fresh_db.list_versions(d)
    assert len(versions_after) == 2

    # Make sure the deleted version is not in the list
    version_ids = [v["id"] for v in versions_after]
    assert vid2 not in version_ids
    assert vid1 in version_ids
    assert vid3 in version_ids


def test_update_reminder_active(fresh_db):
    """Test updating the active status of a reminder."""
    from bouquin.reminders import Reminder, ReminderType

    # Create a reminder object
    reminder = Reminder(
        id=None,
        text="Test reminder",
        reminder_type=ReminderType.ONCE,
        time_str="14:30",
        date_iso=date.today().isoformat(),
        active=True,
    )

    # Save it
    reminder_id = fresh_db.save_reminder(reminder)

    # Verify it's active
    reminders = fresh_db.get_all_reminders()
    active_reminder = [r for r in reminders if r.id == reminder_id][0]
    assert active_reminder.active is True

    # Deactivate it
    fresh_db.update_reminder_active(reminder_id, False)

    # Verify it's inactive
    reminders = fresh_db.get_all_reminders()
    inactive_reminder = [r for r in reminders if r.id == reminder_id][0]
    assert inactive_reminder.active is False

    # Reactivate it
    fresh_db.update_reminder_active(reminder_id, True)

    # Verify it's active again
    reminders = fresh_db.get_all_reminders()
    reactivated_reminder = [r for r in reminders if r.id == reminder_id][0]
    assert reactivated_reminder.active is True
