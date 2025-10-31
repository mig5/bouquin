from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlcipher3 import dbapi2 as sqlite


@dataclass
class DBConfig:
    path: Path
    key: str


class DBManager:
    def __init__(self, cfg: DBConfig):
        self.cfg = cfg
        self.conn: sqlite.Connection | None = None

    def connect(self) -> bool:
        # Ensure parent dir exists
        self.cfg.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite.connect(str(self.cfg.path))
        cur = self.conn.cursor()
        cur.execute(f"PRAGMA key = '{self.cfg.key}';")
        cur.execute("PRAGMA cipher_compatibility = 4;")
        cur.execute("PRAGMA journal_mode = WAL;")
        self.conn.commit()
        try:
            self._integrity_ok()
        except Exception:
            self.conn.close()
            self.conn = None
            return False
        self._ensure_schema()
        return True

    def _integrity_ok(self) -> bool:
        cur = self.conn.cursor()
        cur.execute("PRAGMA cipher_integrity_check;")
        rows = cur.fetchall()

        # OK
        if not rows:
            return

        # Not OK
        details = "; ".join(str(r[0]) for r in rows if r and r[0] is not None)
        raise sqlite.IntegrityError(
            "SQLCipher integrity check failed"
            + (f": {details}" if details else f" ({len(rows)} issue(s) reported)")
        )

    def _ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                date TEXT PRIMARY KEY, -- ISO yyyy-MM-dd
                content TEXT NOT NULL
            );
            """
        )
        cur.execute("PRAGMA user_version = 1;")
        self.conn.commit()

    def get_entry(self, date_iso: str) -> str:
        cur = self.conn.cursor()
        cur.execute("SELECT content FROM entries WHERE date = ?;", (date_iso,))
        row = cur.fetchone()
        return row[0] if row else ""

    def upsert_entry(self, date_iso: str, content: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO entries(date, content) VALUES(?, ?)
            ON CONFLICT(date) DO UPDATE SET content = excluded.content;
            """,
            (date_iso, content),
        )
        self.conn.commit()

    def dates_with_content(self) -> list[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT date FROM entries WHERE TRIM(content) <> '';")
        return [r[0] for r in cur.fetchall()]

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None
