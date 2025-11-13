import pytest
import json, csv
import datetime as dt
from sqlcipher3 import dbapi2 as sqlite
from bouquin.db import DBManager


def _today():
    return dt.date.today().isoformat()


def _yesterday():
    return (dt.date.today() - dt.timedelta(days=1)).isoformat()


def _tomorrow():
    return (dt.date.today() + dt.timedelta(days=1)).isoformat()


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
    assert any(d == _today() for d, _ in hits)
    assert any(d == _tomorrow() for d, _ in hits)


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

    txt_path = tmp_path / "export.txt"
    fresh_db.export_txt(entries, str(txt_path))
    assert txt_path.exists() and txt_path.read_text().strip()

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
