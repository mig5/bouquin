import pytest
import json, csv
import datetime as dt

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
