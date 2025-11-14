from __future__ import annotations

import csv
import hashlib
import html
import json

from dataclasses import dataclass
from pathlib import Path
from sqlcipher3 import dbapi2 as sqlite
from typing import List, Sequence, Tuple


from . import strings

Entry = Tuple[str, str]
TagRow = Tuple[int, str, str]

_TAG_COLORS = [
    "#FFB3BA",  # soft red
    "#FFDFBA",  # soft orange
    "#FFFFBA",  # soft yellow
    "#BAFFC9",  # soft green
    "#BAE1FF",  # soft blue
    "#E0BAFF",  # soft purple
    "#FFC4B3",  # soft coral
    "#FFD8B1",  # soft peach
    "#FFF1BA",  # soft light yellow
    "#E9FFBA",  # soft lime
    "#CFFFE5",  # soft mint
    "#BAFFF5",  # soft aqua
    "#BAF0FF",  # soft cyan
    "#C7E9FF",  # soft sky blue
    "#C7CEFF",  # soft periwinkle
    "#F0BAFF",  # soft lavender pink
    "#FFBAF2",  # soft magenta
    "#FFD1F0",  # soft pink
    "#EBD5C7",  # soft beige
    "#EAEAEA",  # soft gray
]


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

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                color TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS ix_tags_name ON tags(name);

            CREATE TABLE IF NOT EXISTS page_tags (
                page_date TEXT NOT NULL,               -- FK to pages.date
                tag_id INTEGER NOT NULL,               -- FK to tags.id
                PRIMARY KEY (page_date, tag_id),
                FOREIGN KEY(page_date) REFERENCES pages(date) ON DELETE CASCADE,
                FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS ix_page_tags_tag_id ON page_tags(tag_id);
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
        Search for entries by term or tag name.
        This only works against the latest version of the page.
        """
        cur = self.conn.cursor()
        q = text.strip()
        pattern = f"%{q.lower()}%"

        rows = cur.execute(
            """
            SELECT DISTINCT p.date, v.content
            FROM pages AS p
            JOIN versions AS v
              ON v.id = p.current_version_id
            LEFT JOIN page_tags pt
              ON pt.page_date = p.date
            LEFT JOIN tags t
                  ON t.id = pt.tag_id
            WHERE TRIM(v.content) <> ''
              AND (
                LOWER(v.content) LIKE ?
                 OR LOWER(COALESCE(t.name, '')) LIKE ?
              )
            ORDER BY p.date DESC;
            """,
            (pattern, pattern),
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

    # -------- Tags: helpers -------------------------------------------

    def _default_tag_colour(self, name: str) -> str:
        """
        Deterministically pick a colour for a tag name from a small palette.
        """
        if not name:
            return "#CCCCCC"
        h = int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16)
        return _TAG_COLORS[h % len(_TAG_COLORS)]

    # -------- Tags: per-page -------------------------------------------

    def get_tags_for_page(self, date_iso: str) -> list[TagRow]:
        """
        Return (id, name, color) for all tags attached to this page/date.
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT t.id, t.name, t.color
            FROM page_tags pt
            JOIN tags t ON t.id = pt.tag_id
            WHERE pt.page_date = ?
            ORDER BY LOWER(t.name);
            """,
            (date_iso,),
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def set_tags_for_page(self, date_iso: str, tag_names: Sequence[str]) -> None:
        """
        Replace the tag set for a page with the given names.
        Creates new tags as needed (with auto colours).
        Tags are case-insensitive - reuses existing tag if found with different case.
        """
        # Normalise + dedupe (case-insensitive)
        clean_names = []
        seen = set()
        for name in tag_names:
            name = name.strip()
            if not name:
                continue
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            clean_names.append(name)

        with self.conn:
            cur = self.conn.cursor()

            # Ensure the page row exists even if there's no content yet
            cur.execute("INSERT OR IGNORE INTO pages(date) VALUES (?);", (date_iso,))

            if not clean_names:
                # Just clear all tags for this page
                cur.execute("DELETE FROM page_tags WHERE page_date=?;", (date_iso,))
                return

            # For each tag name, check if it exists with different casing
            # If so, reuse that existing tag; otherwise create new
            final_tag_names = []
            for name in clean_names:
                # Look for existing tag (case-insensitive)
                existing = cur.execute(
                    "SELECT name FROM tags WHERE LOWER(name) = LOWER(?);", (name,)
                ).fetchone()

                if existing:
                    # Use the existing tag's exact name
                    final_tag_names.append(existing["name"])
                else:
                    # Create new tag with the provided casing
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO tags(name, color)
                        VALUES (?, ?);
                        """,
                        (name, self._default_tag_colour(name)),
                    )
                    final_tag_names.append(name)

            # Lookup ids for the final tag names
            placeholders = ",".join("?" for _ in final_tag_names)
            rows = cur.execute(
                f"""
                SELECT id, name
                FROM tags
                WHERE name IN ({placeholders});
                """,
                tuple(final_tag_names),
            ).fetchall()
            ids_by_name = {r["name"]: r["id"] for r in rows}

            # Reset page_tags for this page
            cur.execute("DELETE FROM page_tags WHERE page_date=?;", (date_iso,))
            for name in final_tag_names:
                tag_id = ids_by_name.get(name)
                if tag_id is not None:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO page_tags(page_date, tag_id)
                        VALUES (?, ?);
                        """,
                        (date_iso, tag_id),
                    )

    # -------- Tags: global management ----------------------------------

    def list_tags(self) -> list[TagRow]:
        """
        Return all tags in the database.
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT id, name, color
            FROM tags
            ORDER BY LOWER(name);
            """
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def update_tag(self, tag_id: int, name: str, color: str) -> None:
        """
        Update a tag's name and colour.
        """
        name = name.strip()
        color = color.strip() or "#CCCCCC"

        try:
            with self.conn:
                cur = self.conn.cursor()
                cur.execute(
                    """
                    UPDATE tags
                    SET name = ?, color = ?
                    WHERE id = ?;
                    """,
                    (name, color, tag_id),
                )
        except sqlite.IntegrityError as e:
            if "UNIQUE constraint failed: tags.name" in str(e):
                raise sqlite.IntegrityError(
                    strings._("tag_already_exists_with_that_name")
                ) from e

    def delete_tag(self, tag_id: int) -> None:
        """
        Delete a tag entirely (removes it from all pages).
        """
        with self.conn:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM page_tags WHERE tag_id=?;", (tag_id,))
            cur.execute("DELETE FROM tags WHERE id=?;", (tag_id,))

    def get_pages_for_tag(self, tag_name: str) -> list[Entry]:
        """
        Return (date, content) for pages that have the given tag.
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT p.date, v.content
            FROM pages AS p
            JOIN versions AS v
              ON v.id = p.current_version_id
            JOIN page_tags pt
              ON pt.page_date = p.date
            JOIN tags t
              ON t.id = pt.tag_id
            WHERE LOWER(t.name) = LOWER(?)
            ORDER BY p.date DESC;
            """,
            (tag_name,),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None
