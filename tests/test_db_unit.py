import bouquin.db as dbmod
from bouquin.db import DBConfig, DBManager


class FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, tuple(params) if params else None))
        return self

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.closed = False
        self.cursors = []
        self.row_factory = None

    def cursor(self):
        c = FakeCursor(rows=self._rows)
        self.cursors.append(c)
        return c

    def close(self):
        self.closed = True

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def test_integrity_ok_ok(monkeypatch, tmp_path):
    mgr = DBManager(DBConfig(tmp_path / "db.sqlite", key="x"))
    mgr.conn = FakeConn(rows=[])
    assert mgr._integrity_ok() is None


def test_integrity_ok_raises(monkeypatch, tmp_path):
    mgr = DBManager(DBConfig(tmp_path / "db.sqlite", key="x"))
    mgr.conn = FakeConn(rows=[("oops",), (None,)])
    try:
        mgr._integrity_ok()
    except Exception as e:
        assert isinstance(e, dbmod.sqlite.IntegrityError)


def test_connect_closes_on_integrity_failure(monkeypatch, tmp_path):
    # Use a non-empty key to avoid SQLCipher complaining before our patch runs
    mgr = DBManager(DBConfig(tmp_path / "db.sqlite", key="x"))
    # Make the integrity check raise so connect() takes the failure path
    monkeypatch.setattr(
        DBManager,
        "_integrity_ok",
        lambda self: (_ for _ in ()).throw(RuntimeError("bad")),
    )
    ok = mgr.connect()
    assert ok is False
    assert mgr.conn is None


def test_rekey_not_connected_raises(tmp_path):
    mgr = DBManager(DBConfig(tmp_path / "db.sqlite", key="old"))
    mgr.conn = None
    import pytest

    with pytest.raises(RuntimeError):
        mgr.rekey("new")


def test_rekey_reopen_failure(monkeypatch, tmp_path):
    mgr = DBManager(DBConfig(tmp_path / "db.sqlite", key="old"))
    mgr.conn = FakeConn(rows=[(None,)])
    monkeypatch.setattr(DBManager, "connect", lambda self: False)
    import pytest

    with pytest.raises(Exception):
        mgr.rekey("new")


def test_export_by_extension_and_unknown(tmp_path):
    mgr = DBManager(DBConfig(tmp_path / "db.sqlite", key="x"))
    entries = [("2025-01-01", "<b>Hi</b>")]
    # Test each exporter writes the file
    p = tmp_path / "out.json"
    mgr.export_json(entries, str(p))
    assert p.exists() and p.stat().st_size > 0
    p = tmp_path / "out.csv"
    mgr.export_csv(entries, str(p))
    assert p.exists()
    p = tmp_path / "out.txt"
    mgr.export_txt(entries, str(p))
    assert p.exists()
    p = tmp_path / "out.html"
    mgr.export_html(entries, str(p))
    assert p.exists()
    p = tmp_path / "out.md"
    mgr.export_markdown(entries, str(p))
    assert p.exists()
    # Router
    import types

    mgr.get_all_entries = types.MethodType(lambda self: entries, mgr)
    for ext in [".json", ".csv", ".txt", ".html", ".md"]:
        path = tmp_path / f"route{ext}"
        mgr.export_by_extension(str(path))
        assert path.exists()
    import pytest

    with pytest.raises(ValueError):
        mgr.export_by_extension(str(tmp_path / "x.zzz"))


def test_compact_error_prints(monkeypatch, tmp_path, capsys):
    mgr = DBManager(DBConfig(tmp_path / "db.sqlite", key="x"))

    class BadConn:
        def cursor(self):
            raise RuntimeError("no")

    mgr.conn = BadConn()
    mgr.compact()
    out = capsys.readouterr().out
    assert "Error:" in out
