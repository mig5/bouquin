from __future__ import annotations

from pathlib import Path
import pytest

from bouquin.db import DBManager, DBConfig

# Use the same sqlite driver as the app (sqlcipher3) to prepare pre-0.1.5 "entries" DBs
from sqlcipher3 import dbapi2 as sqlite


def connect_raw_sqlcipher(db_path: Path, key: str):
    conn = sqlite.connect(str(db_path))
    conn.row_factory = sqlite.Row
    cur = conn.cursor()
    cur.execute(f"PRAGMA key = '{key}';")
    cur.execute("PRAGMA foreign_keys = ON;")
    cur.execute("PRAGMA journal_mode = WAL;").fetchone()
    return conn


def test_migration_from_legacy_entries_table(cfg: DBConfig, tmp_path: Path):
    # Prepare a "legacy" DB that has only entries(date, content) and no pages/versions
    db_path = cfg.path
    conn = connect_raw_sqlcipher(db_path, cfg.key)
    cur = conn.cursor()
    cur.execute("CREATE TABLE entries(date TEXT PRIMARY KEY, content TEXT NOT NULL);")
    cur.execute(
        "INSERT INTO entries(date, content) VALUES(?, ?);",
        ("2025-01-02", "<p>Hello</p>"),
    )
    conn.commit()
    conn.close()

    # Now use the real DBManager, which will run _ensure_schema and migrate
    mgr = DBManager(cfg)
    assert mgr.connect() is True

    # After migration, legacy table should be gone and content reachable via get_entry
    text = mgr.get_entry("2025-01-02")
    assert "Hello" in text

    cur = mgr.conn.cursor()
    # entries table should be dropped
    with pytest.raises(sqlite.OperationalError):
        cur.execute("SELECT count(*) FROM entries;").fetchone()

    # pages & versions exist and head points to v1
    rows = cur.execute(
        "SELECT current_version_id FROM pages WHERE date='2025-01-02'"
    ).fetchone()
    assert rows is not None and rows["current_version_id"] is not None
    vers = mgr.list_versions("2025-01-02")
    assert vers and vers[0]["version_no"] == 1 and vers[0]["is_current"] == 1


def test_save_new_version_requires_connection_raises(cfg: DBConfig):
    mgr = DBManager(cfg)
    with pytest.raises(RuntimeError):
        mgr.save_new_version("2025-01-03", "<p>x</p>")


def _bootstrap_db(cfg: DBConfig) -> DBManager:
    mgr = DBManager(cfg)
    assert mgr.connect() is True
    return mgr


def test_revert_to_version_by_number_and_id_and_errors(cfg: DBConfig):
    mgr = _bootstrap_db(cfg)
    # Create two versions for the same date
    ver1_id, ver1_no = mgr.save_new_version("2025-01-04", "<p>v1</p>", note="init")
    ver2_id, ver2_no = mgr.save_new_version("2025-01-04", "<p>v2</p>", note="edit")
    assert ver1_no == 1 and ver2_no == 2

    # Revert using version_id
    mgr.revert_to_version(date_iso="2025-01-04", version_id=ver2_id)
    cur = mgr.conn.cursor()
    head2 = cur.execute(
        "SELECT current_version_id FROM pages WHERE date=?", ("2025-01-04",)
    ).fetchone()[0]
    assert head2 == ver2_id

    # Error: version_id belongs to a different date
    other_id, _ = mgr.save_new_version("2025-01-05", "<p>other</p>")
    with pytest.raises(ValueError):
        mgr.revert_to_version(date_iso="2025-01-04", version_id=other_id)


def test_export_by_extension_and_compact(cfg: DBConfig, tmp_path: Path):
    mgr = _bootstrap_db(cfg)
    # Seed a couple of entries
    mgr.save_new_version("2025-01-06", "<p>A</p>")
    mgr.save_new_version("2025-01-07", "<p>B</p>")

    # Prepare output files
    out = tmp_path
    exts = [
        ".json",
        ".csv",
        ".txt",
        ".html",
        ".sql",
    ]  # exclude .md due to different signature
    for ext in exts:
        path = out / f"export{ext}"
        mgr.export_by_extension(str(path))
        assert path.exists() and path.stat().st_size > 0

    # Markdown export uses a different signature (entries + path)
    entries = mgr.get_all_entries()
    md_path = out / "export.md"
    mgr.export_markdown(entries, str(md_path))
    assert md_path.exists() and md_path.stat().st_size > 0

    # Run VACUUM path
    mgr.compact()  # should not raise
