from __future__ import annotations

import csv
import html
import json

from dataclasses import dataclass
from pathlib import Path
from sqlcipher3 import dbapi2 as sqlite
from typing import List, Sequence, Tuple

from . import strings

Entry = Tuple[str, str]


@dataclass
class DBConfig:
    path: Path
    key: str
    idle_minutes: int = 15  # 0 = never lock
    theme: str = "system"
    move_todos: bool = False
    locale: str = "en"


class DBManager:
    def __init__(self, cfg: DBConfig):
        self.cfg = cfg
        self.conn: sqlite.Connection | None = None

    def connect(self) -> bool:
        """
        Open, decrypt and install schema on the database.
        """
        # Ensure parent dir exists
        self.cfg.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite.connect(str(self.cfg.path))
        self.conn.row_factory = sqlite.Row
        cur = self.conn.cursor()
        cur.execute(f"PRAGMA key = '{self.cfg.key}';")
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute("PRAGMA journal_mode = WAL;").fetchone()
        try:
            self._integrity_ok()
        except Exception:
            self.conn.close()
            self.conn = None
            return False
        self._ensure_schema()
        return True

    def _integrity_ok(self) -> bool:
        """
        Runs the cipher_integrity_check PRAGMA on the database.
        """
        cur = self.conn.cursor()
        cur.execute("PRAGMA cipher_integrity_check;")
        rows = cur.fetchall()

        # OK: nothing returned
        if not rows:
            return

        # Not OK: rows of problems returned
        details = "; ".join(str(r[0]) for r in rows if r and r[0] is not None)
        raise sqlite.IntegrityError(
            strings._("db_sqlcipher_integrity_check_failed")
            + (
                f": {details}"
                if details
                else f" ({len(rows)} {strings._('db_issues_reported')})"
            )
        )

    def _ensure_schema(self) -> None:
        """
        Install the expected schema on the database.
        We also handle upgrades here.
        """
        cur = self.conn.cursor()
        # Always keep FKs on
        cur.execute("PRAGMA foreign_keys = ON;")

        # Create new versioned schema if missing (< 0.1.5)
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS pages (
                date TEXT PRIMARY KEY,                 -- yyyy-MM-dd
                current_version_id INTEGER,
                FOREIGN KEY(current_version_id) REFERENCES versions(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS versions (
                id INTEGER PRIMARY KEY,
                date TEXT NOT NULL,                    -- FK to pages.date
                version_no INTEGER NOT NULL,           -- 1,2,3… per date
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                note   TEXT,
                content TEXT NOT NULL,
                FOREIGN KEY(date) REFERENCES pages(date) ON DELETE CASCADE
            );

            CREATE UNIQUE INDEX IF NOT EXISTS ux_versions_date_ver ON versions(date, version_no);
            CREATE INDEX IF NOT EXISTS ix_versions_date_created ON versions(date, created_at);
            """
        )
        self.conn.commit()

    def rekey(self, new_key: str) -> None:
        """
        Change the SQLCipher passphrase in-place, then reopen the connection
        with the new key to verify.
        """
        cur = self.conn.cursor()
        # Change the encryption key of the currently open database
        cur.execute(f"PRAGMA rekey = '{new_key}';").fetchone()
        self.conn.commit()

        # Close and reopen with the new key to verify and restore PRAGMAs
        self.conn.close()
        self.conn = None
        self.cfg.key = new_key
        if not self.connect():
            raise sqlite.Error(strings._("db_reopen_failed_after_rekey"))

    def get_entry(self, date_iso: str) -> str:
        """
        Get a single entry by its date.
        """
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT v.content
            FROM pages p
            JOIN versions v ON v.id = p.current_version_id
            WHERE p.date = ?;
            """,
            (date_iso,),
        ).fetchone()
        return row[0] if row else ""

    def search_entries(self, text: str) -> list[str]:
        """
        Search for entries by term. This only works against the latest
        version of the page.
        """
        cur = self.conn.cursor()
        pattern = f"%{text}%"
        rows = cur.execute(
            """
            SELECT p.date, v.content
            FROM pages AS p
            JOIN versions AS v
              ON v.id = p.current_version_id
            WHERE TRIM(v.content) <> ''
              AND v.content LIKE LOWER(?) ESCAPE '\\'
            ORDER BY p.date DESC;
            """,
            (pattern,),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def dates_with_content(self) -> list[str]:
        """
        Find all entries and return the dates of them.
        This is used to mark the calendar days in bold if they contain entries.
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT p.date
            FROM pages p
            JOIN versions v
              ON v.id = p.current_version_id
            WHERE TRIM(v.content) <> ''
            ORDER BY p.date;
            """
        ).fetchall()
        return [r[0] for r in rows]

    # ------------------------- Versioning logic here ------------------------#
    def save_new_version(
        self,
        date_iso: str,
        content: str,
        note: str | None = None,
        set_current: bool = True,
    ) -> tuple[int, int]:
        """
        Append a new version for this date. Returns (version_id, version_no).
        If set_current=True, flips the page head to this new version.
        """
        with self.conn:  # transaction
            cur = self.conn.cursor()
            # Ensure page row exists
            cur.execute("INSERT OR IGNORE INTO pages(date) VALUES (?);", (date_iso,))
            # Next version number
            row = cur.execute(
                "SELECT COALESCE(MAX(version_no), 0) AS maxv FROM versions WHERE date=?;",
                (date_iso,),
            ).fetchone()
            next_ver = int(row["maxv"]) + 1
            # Insert the version
            cur.execute(
                "INSERT INTO versions(date, version_no, content, note) "
                "VALUES (?,?,?,?);",
                (date_iso, next_ver, content, note),
            )
            ver_id = cur.lastrowid
            if set_current:
                cur.execute(
                    "UPDATE pages SET current_version_id=? WHERE date=?;",
                    (ver_id, date_iso),
                )
            return ver_id, next_ver

    def list_versions(self, date_iso: str) -> list[dict]:
        """
        Returns history for a given date (newest first), including which one is current.
        Each item: {id, version_no, created_at, note, is_current}
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT v.id, v.version_no, v.created_at, v.note,
                   CASE WHEN v.id = p.current_version_id THEN 1 ELSE 0 END AS is_current
            FROM versions v
            LEFT JOIN pages p ON p.date = v.date
            WHERE v.date = ?
            ORDER BY v.version_no DESC;
            """,
            (date_iso,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_version(self, *, version_id: int) -> dict | None:
        """
        Fetch a specific version by version_id.
        Returns a dict with keys: id, date, version_no, created_at, note, content.
        """
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT id, date, version_no, created_at, note, content "
            "FROM versions WHERE id=?;",
            (version_id,),
        ).fetchone()
        return dict(row) if row else None

    def revert_to_version(self, date_iso: str, version_id: int) -> None:
        """
        Point the page head (pages.current_version_id) to an existing version.
        """
        cur = self.conn.cursor()

        # Ensure that version_id belongs to the given date
        row = cur.execute(
            "SELECT date FROM versions WHERE id=?;", (version_id,)
        ).fetchone()
        if row is None or row["date"] != date_iso:
            raise ValueError(
                strings._("db_version_id_does_not_belong_to_the_given_date")
            )

        with self.conn:
            cur.execute(
                "UPDATE pages SET current_version_id=? WHERE date=?;",
                (version_id, date_iso),
            )

    # ------------------------- Export logic here ------------------------#
    def get_all_entries(self) -> List[Entry]:
        """
        Get all entries. Used for exports.
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT p.date, v.content
            FROM pages p
            JOIN versions v ON v.id = p.current_version_id
            ORDER BY p.date;
            """
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def export_json(self, entries: Sequence[Entry], file_path: str) -> None:
        """
        Export to json.
        """
        data = [{"date": d, "content": c} for d, c in entries]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def export_csv(self, entries: Sequence[Entry], file_path: str) -> None:
        """
        Export pages to CSV.
        """
        # utf-8-sig adds a BOM so Excel opens as UTF-8 by default.
        with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "content"])  # header
            writer.writerows(entries)

    def export_txt(
        self,
        entries: Sequence[Entry],
        file_path: str,
        separator: str = "\n\n— — — — —\n\n",
    ) -> None:
        """
        Strip the the latest version of the pages to a text file.
        """
        with open(file_path, "w", encoding="utf-8") as f:
            for i, (d, c) in enumerate(entries):
                f.write(f"{d}\n{c}\n")
                if i < len(entries) - 1:
                    f.write(separator)

    def export_html(
        self, entries: Sequence[Entry], file_path: str, title: str = "Bouquin export"
    ) -> None:
        """
        Export to HTML with a heading.
        """
        parts = [
            "<!doctype html>",
            '<html lang="en">',
            '<meta charset="utf-8">',
            f"<title>{html.escape(title)}</title>",
            "<style>body{font:16px/1.5 system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;padding:24px;max-width:900px;margin:auto;}",
            "article{padding:16px 0;border-bottom:1px solid #ddd;} time{font-weight:600;color:#333;} section{margin-top:8px;}</style>",
            "<body>",
            f"<h1>{html.escape(title)}</h1>",
        ]
        for d, c in entries:
            parts.append(
                f"<article><header><time>{html.escape(d)}</time></header><section>{c}</section></article>"
            )
        parts.append("</body></html>")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(parts))

    def export_markdown(
        self, entries: Sequence[Entry], file_path: str, title: str = "Bouquin export"
    ) -> None:
        """
        Export the data to a markdown file. Since the data is already Markdown,
        nothing more to do.
        """
        parts = []
        for d, c in entries:
            parts.append(f"# {d}")
            parts.append(c)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(parts))

    def export_sql(self, file_path: str) -> None:
        """
        Exports the encrypted database as plaintext SQL.
        """
        cur = self.conn.cursor()
        cur.execute(f"ATTACH DATABASE '{file_path}' AS plaintext KEY '';")
        cur.execute("SELECT sqlcipher_export('plaintext')")
        cur.execute("DETACH DATABASE plaintext")

    def export_sqlcipher(self, file_path: str) -> None:
        """
        Exports the encrypted database as an encrypted database with the same key.
        Intended for Bouquin-compatible backups.
        """
        cur = self.conn.cursor()
        cur.execute(f"ATTACH DATABASE '{file_path}' AS backup KEY '{self.cfg.key}'")
        cur.execute("SELECT sqlcipher_export('backup')")
        cur.execute("DETACH DATABASE backup")

    def compact(self) -> None:
        """
        Runs VACUUM on the db.
        """
        try:
            cur = self.conn.cursor()
            cur.execute("VACUUM")
        except Exception as e:
            print(f"{strings._('error')}: {e}")

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None
