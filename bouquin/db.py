from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import html
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import markdown
from sqlcipher4 import Binary
from sqlcipher4 import dbapi2 as sqlite

from . import strings

Entry = Tuple[str, str]
TagRow = Tuple[int, str, str]
ProjectRow = Tuple[int, str]  # (id, name)
ActivityRow = Tuple[int, str]  # (id, name)
TimeLogRow = Tuple[
    int,  # id
    str,  # page_date (yyyy-MM-dd)
    int,
    str,  # project_id, project_name
    int,
    str,  # activity_id, activity_name
    int,  # minutes
    str | None,  # note
]
DocumentRow = Tuple[
    int,  # id
    int,  # project_id
    str,  # project_name
    str,  # file_name
    str | None,  # description
    int,  # size_bytes
    str,  # uploaded_at (ISO)
]
ProjectBillingRow = Tuple[
    int,  # project_id
    int,  # hourly_rate_cents
    str,  # currency
    str | None,  # tax_label
    float | None,  # tax_rate_percent
    str | None,  # client_name
    str | None,  # client_company
    str | None,  # client_address
    str | None,  # client_email
]
CompanyProfileRow = Tuple[
    str | None,  # name
    str | None,  # address
    str | None,  # phone
    str | None,  # email
    str | None,  # tax_id
    str | None,  # payment_details
    bytes | None,  # logo
]

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
    move_todos_include_weekends: bool = False
    tags: bool = True
    time_log: bool = True
    reminders: bool = True
    reminders_webhook_url: str = (None,)
    reminders_webhook_secret: str = (None,)
    documents: bool = True
    invoicing: bool = False
    locale: str = "en"
    font_size: int = 11


class DBManager:
    # Allow list of invoice columns allowed for dynamic field helpers
    _INVOICE_COLUMN_ALLOWLIST = frozenset(
        {
            "invoice_number",
            "issue_date",
            "due_date",
            "currency",
            "tax_label",
            "tax_rate_percent",
            "subtotal_cents",
            "tax_cents",
            "total_cents",
            "detail_mode",
            "paid_at",
            "payment_note",
            "document_id",
        }
    )

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

            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS time_log (
                id INTEGER PRIMARY KEY,
                page_date TEXT NOT NULL,               -- FK to pages.date (yyyy-MM-dd)
                project_id INTEGER NOT NULL,           -- FK to projects.id
                activity_id INTEGER NOT NULL,          -- FK to activities.id
                minutes INTEGER NOT NULL,              -- duration in minutes
                note TEXT,
                created_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ','now')
                ),
                FOREIGN KEY(page_date) REFERENCES pages(date) ON DELETE CASCADE,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE RESTRICT,
                FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE RESTRICT
            );

            CREATE INDEX IF NOT EXISTS ix_time_log_date
                ON time_log(page_date);
            CREATE INDEX IF NOT EXISTS ix_time_log_project
                ON time_log(project_id);
            CREATE INDEX IF NOT EXISTS ix_time_log_activity
                ON time_log(activity_id);

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                time_str TEXT NOT NULL,                -- HH:MM
                reminder_type TEXT NOT NULL,           -- once|daily|weekdays|weekly
                weekday INTEGER,                       -- 0-6 for weekly (0=Mon)
                date_iso TEXT,                         -- for once type
                active INTEGER NOT NULL DEFAULT 1,     -- 0=inactive, 1=active
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );

            CREATE INDEX IF NOT EXISTS ix_reminders_active
                ON reminders(active);

            CREATE TABLE IF NOT EXISTS project_documents (
                id           INTEGER PRIMARY KEY,
                project_id   INTEGER NOT NULL,           -- FK to projects.id
                file_name    TEXT    NOT NULL,           -- original filename
                mime_type    TEXT,                       -- optional
                description  TEXT,
                size_bytes   INTEGER NOT NULL,
                uploaded_at  TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%d','now')
                ),
                data         BLOB    NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE RESTRICT
            );

            CREATE INDEX IF NOT EXISTS ix_project_documents_project
                ON project_documents(project_id);

            -- New: tags attached to documents (like page_tags, but for docs)
            CREATE TABLE IF NOT EXISTS document_tags (
                document_id INTEGER NOT NULL,            -- FK to project_documents.id
                tag_id      INTEGER NOT NULL,            -- FK to tags.id
                PRIMARY KEY (document_id, tag_id),
                FOREIGN KEY(document_id) REFERENCES project_documents(id) ON DELETE CASCADE,
                FOREIGN KEY(tag_id)      REFERENCES tags(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS ix_document_tags_tag_id
                ON document_tags(tag_id);

            CREATE TABLE IF NOT EXISTS project_billing (
                project_id        INTEGER PRIMARY KEY
                                   REFERENCES projects(id) ON DELETE CASCADE,
                hourly_rate_cents INTEGER NOT NULL DEFAULT 0,
                currency          TEXT NOT NULL DEFAULT 'AUD',
                tax_label         TEXT,
                tax_rate_percent  REAL,
                client_name       TEXT, -- contact person
                client_company    TEXT, -- business name
                client_address    TEXT,
                client_email      TEXT
            );

            CREATE TABLE IF NOT EXISTS company_profile (
                id       INTEGER PRIMARY KEY CHECK (id = 1),
                name     TEXT,
                address  TEXT,
                phone    TEXT,
                email    TEXT,
                tax_id   TEXT,
                payment_details TEXT,
                logo     BLOB
            );

            CREATE TABLE IF NOT EXISTS invoices (
                id               INTEGER PRIMARY KEY,
                project_id       INTEGER NOT NULL
                                 REFERENCES projects(id) ON DELETE RESTRICT,
                invoice_number   TEXT NOT NULL,
                issue_date       TEXT NOT NULL, -- yyyy-MM-dd
                due_date         TEXT,
                currency         TEXT NOT NULL,
                tax_label        TEXT,
                tax_rate_percent REAL,
                subtotal_cents   INTEGER NOT NULL,
                tax_cents        INTEGER NOT NULL,
                total_cents      INTEGER NOT NULL,
                detail_mode      TEXT NOT NULL,      -- 'detailed' | 'summary'
                paid_at          TEXT,
                payment_note     TEXT,
                document_id      INTEGER,
                FOREIGN KEY(document_id) REFERENCES project_documents(id)
                    ON DELETE SET NULL,
                UNIQUE(project_id, invoice_number)
            );

            CREATE INDEX IF NOT EXISTS ix_invoices_project
                ON invoices(project_id);

            CREATE TABLE IF NOT EXISTS invoice_line_items (
                id          INTEGER PRIMARY KEY,
                invoice_id  INTEGER NOT NULL
                            REFERENCES invoices(id) ON DELETE CASCADE,
                description TEXT NOT NULL,
                hours       REAL NOT NULL,
                rate_cents  INTEGER NOT NULL,
                amount_cents INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS ix_invoice_line_items_invoice
                ON invoice_line_items(invoice_id);

            CREATE TABLE IF NOT EXISTS invoice_time_log (
                invoice_id  INTEGER NOT NULL
                            REFERENCES invoices(id) ON DELETE CASCADE,
                time_log_id INTEGER NOT NULL
                            REFERENCES time_log(id) ON DELETE RESTRICT,
                PRIMARY KEY (invoice_id, time_log_id)
            );
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

    def search_entries(self, text: str) -> list[tuple[str, str, str, str, str | None]]:
        """
        Search for entries by term or tag name.
        Returns both pages and documents.

        kind = "page" or "document"
        key  = date_iso (page) or str(doc_id) (document)
        title = heading for the result ("YYYY-MM-DD" or "Document")
        text  = source text for the snippet
        aux   = extra info (file_name for documents, else None)
        """
        cur = self.conn.cursor()
        q = text.strip()
        if not q:
            return []

        pattern = f"%{q.lower()}%"

        results: list[tuple[str, str, str, str, str | None]] = []

        # --- Pages: content or tag matches ---------------------------------
        page_rows = cur.execute(
            """
            SELECT DISTINCT p.date AS date_iso, v.content
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

        for r in page_rows:
            date_iso = r["date_iso"]
            content = r["content"]
            results.append(("page", date_iso, date_iso, content, None))

        # --- Documents: file name, description, or tag matches -------------
        doc_rows = cur.execute(
            """
            SELECT DISTINCT
                d.id          AS doc_id,
                d.file_name   AS file_name,
                d.uploaded_at AS uploaded_at,
                COALESCE(d.description, '') AS description,
                COALESCE(t.name, '')        AS tag_name
            FROM project_documents AS d
            LEFT JOIN document_tags AS dt
              ON dt.document_id = d.id
            LEFT JOIN tags AS t
              ON t.id = dt.tag_id
            WHERE
                LOWER(d.file_name) LIKE ?
                OR LOWER(COALESCE(d.description, '')) LIKE ?
                OR LOWER(COALESCE(t.name, '')) LIKE ?
            ORDER BY LOWER(d.file_name);
            """,
            (pattern, pattern, pattern),
        ).fetchall()

        for r in doc_rows:
            doc_id = r["doc_id"]
            file_name = r["file_name"]
            description = r["description"] or ""
            uploaded_at = r["uploaded_at"]
            # Simple snippet source: file name + description
            text_src = f"{file_name}\n{description}".strip()

            results.append(
                (
                    "document",
                    str(doc_id),
                    strings._("search_result_heading_document") + f" ({uploaded_at})",
                    text_src,
                    file_name,
                )
            )

        return results

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

    def delete_version(self, *, version_id: int) -> bool | None:
        """
        Delete a specific version by version_id.
        """
        cur = self.conn.cursor()
        with self.conn:
            cur.execute(
                "DELETE FROM versions WHERE id=?;",
                (version_id,),
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
            "<style>"
            "body{font:16px/1.5 system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
            "padding:24px;max-width:900px;margin:auto;}"
            "article{padding:16px 0;border-bottom:1px solid #ddd;}"
            "article header time{font-weight:600;color:#333;}"
            "section{margin-top:8px;}"
            "table{border-collapse:collapse;margin-top:8px;}"
            "th,td{border:1px solid #ddd;padding:4px 8px;text-align:left;}"
            "</style>",
            "<body>",
            f"<h1>{html.escape(title)}</h1>",
        ]
        for d, c in entries:
            body_html = markdown.markdown(
                c,
                extensions=[
                    "extra",
                    "nl2br",
                ],
                output_format="html5",
            )

            parts.append(
                f"<article>"
                f"<header><time>{html.escape(d)}</time></header>"
                f"<section>{body_html}</section>"
                f"</article>"
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
        h = int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16)  # nosec
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
                """,  # nosec
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

    def add_tag(self, name: str, color: str) -> None:
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
                    INSERT INTO tags
                    (name, color)
                    VALUES (?, ?);
                    """,
                    (name, color),
                )
        except sqlite.IntegrityError as e:
            if "UNIQUE constraint failed: tags.name" in str(e):
                raise sqlite.IntegrityError(
                    strings._("tag_already_exists_with_that_name")
                ) from e

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
        Delete a tag entirely (removes it from all pages and documents).
        """
        with self.conn:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM page_tags WHERE tag_id=?;", (tag_id,))
            cur.execute("DELETE FROM document_tags WHERE tag_id=?;", (tag_id,))
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

    # ---------- helpers for word counting ----------
    def _strip_markdown(self, text: str) -> str:
        """
        Cheap markdown-ish stripper for word counting.
        We only need approximate numbers.
        """
        if not text:
            return ""

        # Remove fenced code blocks
        text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
        # Remove inline code
        text = re.sub(r"`[^`]+`", " ", text)
        # [text](url) → text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # Remove emphasis markers, headings, etc.
        text = re.sub(r"[#*_>]+", " ", text)
        # Strip simple HTML tags
        text = re.sub(r"<[^>]+>", " ", text)

        return text

    def _count_words(self, text: str) -> int:
        text = self._strip_markdown(text)
        words = re.findall(r"\b\w+\b", text, flags=re.UNICODE)
        return len(words)

    def gather_stats(self):
        """Compute all the numbers the Statistics dialog needs in one place."""

        # 1) pages with content (current version only)
        try:
            pages_with_content_list = self.dates_with_content()
        except Exception:
            pages_with_content_list = []
        pages_with_content = len(pages_with_content_list)

        cur = self.conn.cursor()

        # 2 & 3) total revisions + page with most revisions + per-date counts
        total_revisions = 0
        page_most_revisions: str | None = None
        page_most_revisions_count = 0
        revisions_by_date: Dict[_dt.date, int] = {}

        rows = cur.execute(
            """
            SELECT date, COUNT(*) AS c
            FROM versions
            GROUP BY date
            ORDER BY date;
            """
        ).fetchall()

        for r in rows:
            date_iso = r["date"]
            c = int(r["c"])
            total_revisions += c

            if c > page_most_revisions_count:
                page_most_revisions_count = c
                page_most_revisions = date_iso

            d = _dt.date.fromisoformat(date_iso)
            revisions_by_date[d] = c

        # 4) total words + per-date words (current version only)
        entries = self.get_all_entries()
        total_words = 0
        words_by_date: Dict[_dt.date, int] = {}

        for date_iso, content in entries:
            wc = self._count_words(content or "")
            total_words += wc
            d = _dt.date.fromisoformat(date_iso)
            words_by_date[d] = wc

        # tags + page with most tags
        rows = cur.execute("SELECT COUNT(*) AS total_unique FROM tags;").fetchall()
        unique_tags = int(rows[0]["total_unique"]) if rows else 0

        rows = cur.execute(
            """
            SELECT page_date, COUNT(*) AS c
            FROM page_tags
            GROUP BY page_date
            ORDER BY c DESC, page_date ASC
            LIMIT 1;
            """
        ).fetchall()

        if rows:
            page_most_tags = rows[0]["page_date"]
            page_most_tags_count = int(rows[0]["c"])
        else:
            page_most_tags = None
            page_most_tags_count = 0

        # 5) Time logging stats (minutes / hours)
        time_minutes_by_date: Dict[_dt.date, int] = {}
        total_time_minutes = 0
        day_most_time: str | None = None
        day_most_time_minutes = 0

        try:
            rows = cur.execute(
                """
                SELECT page_date, SUM(minutes) AS total_minutes
                FROM time_log
                GROUP BY page_date
                ORDER BY page_date;
                """
            ).fetchall()
        except Exception:
            rows = []

        for r in rows:
            date_iso = r["page_date"]
            if not date_iso:
                continue
            m = int(r["total_minutes"] or 0)
            total_time_minutes += m
            if m > day_most_time_minutes:
                day_most_time_minutes = m
                day_most_time = date_iso
            try:
                d = _dt.date.fromisoformat(date_iso)
            except Exception:  # nosec B112
                continue
            time_minutes_by_date[d] = m

        # Project with most logged time
        project_most_minutes_name: str | None = None
        project_most_minutes = 0

        try:
            rows = cur.execute(
                """
                SELECT p.name AS project_name,
                       SUM(t.minutes) AS total_minutes
                FROM time_log t
                JOIN projects p ON p.id = t.project_id
                GROUP BY t.project_id, p.name
                ORDER BY total_minutes DESC, LOWER(project_name) ASC
                LIMIT 1;
                """
            ).fetchall()
        except Exception:
            rows = []

        if rows:
            project_most_minutes_name = rows[0]["project_name"]
            project_most_minutes = int(rows[0]["total_minutes"] or 0)

        # Activity with most logged time
        activity_most_minutes_name: str | None = None
        activity_most_minutes = 0

        try:
            rows = cur.execute(
                """
                SELECT a.name AS activity_name,
                       SUM(t.minutes) AS total_minutes
                FROM time_log t
                JOIN activities a ON a.id = t.activity_id
                GROUP BY t.activity_id, a.name
                ORDER BY total_minutes DESC, LOWER(activity_name) ASC
                LIMIT 1;
                """
            ).fetchall()
        except Exception:
            rows = []

        if rows:
            activity_most_minutes_name = rows[0]["activity_name"]
            activity_most_minutes = int(rows[0]["total_minutes"] or 0)

        # 6) Reminder stats
        reminders_by_date: Dict[_dt.date, int] = {}
        total_reminders = 0
        day_most_reminders: str | None = None
        day_most_reminders_count = 0

        try:
            rows = cur.execute(
                """
                SELECT substr(created_at, 1, 10) AS date_iso,
                       COUNT(*)                    AS c
                FROM reminders
                GROUP BY date_iso
                ORDER BY date_iso;
                """
            ).fetchall()
        except Exception:
            rows = []

        for r in rows:
            date_iso = r["date_iso"]
            if not date_iso:
                continue
            c = int(r["c"] or 0)
            total_reminders += c
            if c > day_most_reminders_count:
                day_most_reminders_count = c
                day_most_reminders = date_iso
            try:
                d = _dt.date.fromisoformat(date_iso)
            except Exception:  # nosec B112
                continue
            reminders_by_date[d] = c

        return (
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
            time_minutes_by_date,
            total_time_minutes,
            day_most_time,
            day_most_time_minutes,
            project_most_minutes_name,
            project_most_minutes,
            activity_most_minutes_name,
            activity_most_minutes,
            reminders_by_date,
            total_reminders,
            day_most_reminders,
            day_most_reminders_count,
        )

    # -------- Time logging: projects & activities ---------------------

    def list_projects(self) -> list[ProjectRow]:
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT id, name FROM projects ORDER BY LOWER(name);"
        ).fetchall()
        return [(r["id"], r["name"]) for r in rows]

    def list_projects_by_id(self, project_id: int) -> str:
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT name FROM projects WHERE id = ?;",
            (project_id,),
        ).fetchone()
        return row["name"] if row else ""

    def add_project(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("empty project name")
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO projects(name) VALUES (?);",
                (name,),
            )
        row = cur.execute(
            "SELECT id, name FROM projects WHERE name = ?;",
            (name,),
        ).fetchone()
        return row["id"]

    def rename_project(self, project_id: int, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            return
        with self.conn:
            self.conn.execute(
                "UPDATE projects SET name = ? WHERE id = ?;",
                (new_name, project_id),
            )

    def delete_project(self, project_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM projects WHERE id = ?;",
                (project_id,),
            )

    def list_activities(self) -> list[ActivityRow]:
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT id, name FROM activities ORDER BY LOWER(name);"
        ).fetchall()
        return [(r["id"], r["name"]) for r in rows]

    def add_activity(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("empty activity name")
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO activities(name) VALUES (?);",
                (name,),
            )
        row = cur.execute(
            "SELECT id, name FROM activities WHERE name = ?;",
            (name,),
        ).fetchone()
        return row["id"]

    def rename_activity(self, activity_id: int, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name:
            return
        with self.conn:
            self.conn.execute(
                "UPDATE activities SET name = ? WHERE id = ?;",
                (new_name, activity_id),
            )

    def delete_activity(self, activity_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM activities WHERE id = ?;",
                (activity_id,),
            )

    # -------- Time logging: entries -----------------------------------

    def add_time_log(
        self,
        date_iso: str,
        project_id: int,
        activity_id: int,
        minutes: int,
        note: str | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.cursor()
            # Ensure a page row exists even if there is no text content yet
            cur.execute("INSERT OR IGNORE INTO pages(date) VALUES (?);", (date_iso,))
            cur.execute(
                """
                INSERT INTO time_log(page_date, project_id, activity_id, minutes, note)
                VALUES (?, ?, ?, ?, ?);
                """,
                (date_iso, project_id, activity_id, minutes, note),
            )
            return cur.lastrowid

    def update_time_log(
        self,
        entry_id: int,
        project_id: int,
        activity_id: int,
        minutes: int,
        note: str | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                UPDATE time_log
                SET project_id = ?, activity_id = ?, minutes = ?, note = ?
                WHERE id = ?;
                """,
                (project_id, activity_id, minutes, note, entry_id),
            )

    def delete_time_log(self, entry_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM time_log WHERE id = ?;",
                (entry_id,),
            )

    def time_log_for_date(self, date_iso: str) -> list[TimeLogRow]:
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT
                t.id,
                t.page_date,
                t.project_id,
                p.name AS project_name,
                t.activity_id,
                a.name AS activity_name,
                t.minutes,
                t.note,
                t.created_at AS created_at
            FROM time_log t
            JOIN projects  p ON p.id = t.project_id
            JOIN activities a ON a.id = t.activity_id
            WHERE t.page_date = ?
            ORDER BY LOWER(p.name), LOWER(a.name), t.id;
            """,
            (date_iso,),
        ).fetchall()

        result: list[TimeLogRow] = []
        for r in rows:
            result.append(
                (
                    r["id"],
                    r["page_date"],
                    r["project_id"],
                    r["project_name"],
                    r["activity_id"],
                    r["activity_name"],
                    r["minutes"],
                    r["note"],
                    r["created_at"],
                )
            )
        return result

    def time_report(
        self,
        project_id: int,
        start_date_iso: str,
        end_date_iso: str,
        granularity: str = "day",  # 'day' | 'week' | 'month' | 'activity' | 'none'
    ) -> list[tuple[str, str, str, int]]:
        """
        Return (time_period, activity_name, total_minutes) tuples between start and end
        for a project, grouped by period and activity.
        time_period is:
          - 'YYYY-MM-DD' for day
          - 'YYYY-WW'    for week
          - 'YYYY-MM'    for month
        For 'activity' granularity, results are grouped by activity only (no time bucket).
        For 'none' granularity, each individual time log entry becomes a row.
        """
        cur = self.conn.cursor()

        if granularity == "none":
            # No grouping: one row per entry
            rows = cur.execute(
                """
                SELECT
                    t.page_date   AS period,
                    a.name        AS activity_name,
                    t.note        AS note,
                    t.minutes     AS total_minutes
                FROM time_log t
                JOIN activities a ON a.id = t.activity_id
                WHERE t.project_id = ?
                  AND t.page_date BETWEEN ? AND ?
                ORDER BY period, LOWER(a.name), t.id;
                """,
                (project_id, start_date_iso, end_date_iso),
            ).fetchall()

            return [
                (r["period"], r["activity_name"], r["note"], r["total_minutes"])
                for r in rows
            ]

        if granularity == "activity":
            rows = cur.execute(
                """
                SELECT
                    a.name          AS activity_name,
                    SUM(t.minutes)  AS total_minutes
                FROM time_log t
                JOIN activities a ON a.id = t.activity_id
                WHERE t.project_id = ?
                  AND t.page_date BETWEEN ? AND ?
                GROUP BY activity_name
                ORDER BY LOWER(activity_name);
                """,
                (project_id, start_date_iso, end_date_iso),
            ).fetchall()

            # period column is unused for activity grouping in the UI, but we keep
            # the tuple shape consistent.
            return [("", r["activity_name"], "", r["total_minutes"]) for r in rows]

        if granularity == "day":
            bucket_expr = "page_date"
        elif granularity == "week":
            # ISO-like year-week; SQLite weeks start at 00
            bucket_expr = "strftime('%Y-%W', page_date)"
        else:  # month
            bucket_expr = "substr(page_date, 1, 7)"  # YYYY-MM

        rows = cur.execute(
            f"""
            SELECT
                {bucket_expr} AS bucket,
                a.name         AS activity_name,
                SUM(t.minutes) AS total_minutes
            FROM time_log t
            JOIN activities a ON a.id = t.activity_id
            WHERE t.project_id = ?
              AND t.page_date BETWEEN ? AND ?
            GROUP BY bucket, activity_name
            ORDER BY bucket, LOWER(activity_name);
            """,  # nosec
            (project_id, start_date_iso, end_date_iso),
        ).fetchall()

        return [(r["bucket"], r["activity_name"], "", r["total_minutes"]) for r in rows]

    def time_report_all(
        self,
        start_date_iso: str,
        end_date_iso: str,
        granularity: str = "day",  # 'day' | 'week' | 'month' | 'activity' | 'none'
    ) -> list[tuple[str, str, str, str, int]]:
        """
        Return (project_name, time_period, activity_name, note, total_minutes)
        across *all* projects between start and end.
        - For 'day'/'week'/'month', grouped by project + period + activity.
        - For 'activity', grouped by project + activity.
        - For 'none', one row per time_log entry.
        """
        cur = self.conn.cursor()

        if granularity == "none":
            # No grouping - one row per time_log record
            rows = cur.execute(
                """
                SELECT
                    p.name       AS project_name,
                    t.page_date  AS period,
                    a.name       AS activity_name,
                    t.note       AS note,
                    t.minutes    AS total_minutes
                FROM time_log t
                JOIN projects  p ON p.id = t.project_id
                JOIN activities a ON a.id = t.activity_id
                WHERE t.page_date BETWEEN ? AND ?
                ORDER BY LOWER(p.name), period, LOWER(activity_name), t.id;
                """,
                (start_date_iso, end_date_iso),
            ).fetchall()

            return [
                (
                    r["project_name"],
                    r["period"],
                    r["activity_name"],
                    r["note"],
                    r["total_minutes"],
                )
                for r in rows
            ]

        if granularity == "activity":
            rows = cur.execute(
                """
                SELECT
                    p.name         AS project_name,
                    a.name         AS activity_name,
                    SUM(t.minutes) AS total_minutes
                FROM time_log t
                JOIN projects  p ON p.id = t.project_id
                JOIN activities a ON a.id = t.activity_id
                WHERE t.page_date BETWEEN ? AND ?
                GROUP BY p.id, activity_name
                ORDER BY LOWER(p.name), LOWER(activity_name);
                """,
                (start_date_iso, end_date_iso),
            ).fetchall()

            return [
                (
                    r["project_name"],
                    "",
                    r["activity_name"],
                    "",
                    r["total_minutes"],
                )
                for r in rows
            ]

        if granularity == "day":
            bucket_expr = "page_date"
        elif granularity == "week":
            bucket_expr = "strftime('%Y-%W', page_date)"
        else:  # month
            bucket_expr = "substr(page_date, 1, 7)"  # YYYY-MM

        rows = cur.execute(
            f"""
            SELECT
                p.name        AS project_name,
                {bucket_expr} AS bucket,
                a.name        AS activity_name,
                SUM(t.minutes) AS total_minutes
            FROM time_log t
            JOIN projects  p ON p.id = t.project_id
            JOIN activities a ON a.id = t.activity_id
            WHERE t.page_date BETWEEN ? AND ?
            GROUP BY p.id, bucket, activity_name
            ORDER BY LOWER(p.name), bucket, LOWER(activity_name);
            """,  # nosec
            (start_date_iso, end_date_iso),
        ).fetchall()

        return [
            (
                r["project_name"],
                r["bucket"],
                r["activity_name"],
                "",
                r["total_minutes"],
            )
            for r in rows
        ]

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    # ------------------------- Reminders logic here ------------------------#
    def save_reminder(self, reminder) -> int:
        """Save or update a reminder. Returns the reminder ID."""
        cur = self.conn.cursor()
        if reminder.id:
            # Update existing
            cur.execute(
                """
                UPDATE reminders
                SET text = ?, time_str = ?, reminder_type = ?,
                    weekday = ?, date_iso = ?, active = ?
                WHERE id = ?
                """,
                (
                    reminder.text,
                    reminder.time_str,
                    reminder.reminder_type.value,
                    reminder.weekday,
                    reminder.date_iso,
                    1 if reminder.active else 0,
                    reminder.id,
                ),
            )
            self.conn.commit()
            return reminder.id
        else:
            # Insert new
            cur.execute(
                """
                INSERT INTO reminders (text, time_str, reminder_type, weekday, date_iso, active)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    reminder.text,
                    reminder.time_str,
                    reminder.reminder_type.value,
                    reminder.weekday,
                    reminder.date_iso,
                    1 if reminder.active else 0,
                ),
            )
            self.conn.commit()
            return cur.lastrowid

    def get_all_reminders(self):
        """Get all reminders."""
        from .reminders import Reminder, ReminderType

        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT id, text, time_str, reminder_type, weekday, date_iso, active
            FROM reminders
            ORDER BY time_str
            """
        ).fetchall()

        result = []
        for r in rows:
            result.append(
                Reminder(
                    id=r["id"],
                    text=r["text"],
                    time_str=r["time_str"],
                    reminder_type=ReminderType(r["reminder_type"]),
                    weekday=r["weekday"],
                    date_iso=r["date_iso"],
                    active=bool(r["active"]),
                )
            )
        return result

    def update_reminder_active(self, reminder_id: int, active: bool) -> None:
        """Update the active status of a reminder."""
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE reminders SET active = ? WHERE id = ?",
            (1 if active else 0, reminder_id),
        )
        self.conn.commit()

    def delete_reminder(self, reminder_id: int) -> None:
        """Delete a reminder."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        self.conn.commit()

    # ------------------------- Documents logic here ------------------------#

    def documents_for_project(self, project_id: int) -> list[DocumentRow]:
        """
        Return metadata for all documents attached to a given project.
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT
                d.id,
                d.project_id,
                p.name AS project_name,
                d.file_name,
                d.description,
                d.size_bytes,
                d.uploaded_at
            FROM project_documents AS d
            JOIN projects AS p ON p.id = d.project_id
            WHERE d.project_id = ?
            ORDER BY d.uploaded_at DESC, LOWER(d.file_name);
            """,
            (project_id,),
        ).fetchall()

        result: list[DocumentRow] = []
        for r in rows:
            result.append(
                (
                    r["id"],
                    r["project_id"],
                    r["project_name"],
                    r["file_name"],
                    r["description"],
                    r["size_bytes"],
                    r["uploaded_at"],
                )
            )
        return result

    def search_documents(self, query: str) -> list[DocumentRow]:
        """Search documents across all projects.

        The search is case-insensitive and matches against:
        - file name
        - description
        - project name
        - tag names associated with the document
        """
        pattern = f"%{query.lower()}%"
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT DISTINCT
                d.id,
                d.project_id,
                p.name AS project_name,
                d.file_name,
                d.description,
                d.size_bytes,
                d.uploaded_at
            FROM project_documents AS d
            LEFT JOIN projects AS p ON p.id = d.project_id
            LEFT JOIN document_tags AS dt ON dt.document_id = d.id
            LEFT JOIN tags AS t ON t.id = dt.tag_id
            WHERE LOWER(d.file_name) LIKE :pat
               OR LOWER(COALESCE(d.description, '')) LIKE :pat
               OR LOWER(COALESCE(p.name, '')) LIKE :pat
               OR LOWER(COALESCE(t.name, '')) LIKE :pat
            ORDER BY d.uploaded_at DESC, LOWER(d.file_name);
            """,
            {"pat": pattern},
        ).fetchall()

        result: list[DocumentRow] = []
        for r in rows:
            result.append(
                (
                    r["id"],
                    r["project_id"],
                    r["project_name"],
                    r["file_name"],
                    r["description"],
                    r["size_bytes"],
                    r["uploaded_at"],
                )
            )
        return result

    def add_document_from_path(
        self,
        project_id: int,
        file_path: str,
        description: str | None = None,
        uploaded_at: str | None = None,
    ) -> int:
        """
        Read a file from disk and store it as a BLOB in project_documents.

        Args:
            project_id: The project to attach the document to
            file_path: Path to the file to upload
            description: Optional description
            uploaded_at: Optional date in YYYY-MM-DD format. If None, uses current date.
        """
        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"File does not exist: {file_path}")

        data = path.read_bytes()
        size_bytes = len(data)
        file_name = path.name
        mime_type, _ = mimetypes.guess_type(str(path))
        mime_type = mime_type or None

        with self.conn:
            cur = self.conn.cursor()
            if uploaded_at is not None:
                # Use explicit date
                cur.execute(
                    """
                    INSERT INTO project_documents
                        (project_id, file_name, mime_type,
                         description, size_bytes, uploaded_at, data)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        project_id,
                        file_name,
                        mime_type,
                        description,
                        size_bytes,
                        uploaded_at,
                        Binary(data),
                    ),
                )
            else:
                # Let DB default to current date
                cur.execute(
                    """
                    INSERT INTO project_documents
                        (project_id, file_name, mime_type,
                         description, size_bytes, data)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (
                        project_id,
                        file_name,
                        mime_type,
                        description,
                        size_bytes,
                        Binary(data),
                    ),
                )
            doc_id = cur.lastrowid or 0

        return int(doc_id)

    def update_document_description(self, doc_id: int, description: str | None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE project_documents SET description = ? WHERE id = ?;",
                (description, doc_id),
            )

    def update_document_uploaded_at(self, doc_id: int, uploaded_at: str) -> None:
        """
        Update the uploaded_at date for a document.

        Args:
            doc_id: Document ID
            uploaded_at: Date in YYYY-MM-DD format
        """
        with self.conn:
            self.conn.execute(
                "UPDATE project_documents SET uploaded_at = ? WHERE id = ?;",
                (uploaded_at, doc_id),
            )

    def delete_document(self, doc_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM project_documents WHERE id = ?;", (doc_id,))

    def document_data(self, doc_id: int) -> bytes:
        """
        Return just the raw bytes for a document.
        """
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT data FROM project_documents WHERE id = ?;",
            (doc_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown document id {doc_id}")
        return bytes(row["data"])

    def get_tags_for_document(self, document_id: int) -> list[TagRow]:
        """
        Return (id, name, color) for all tags attached to this document.
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT t.id, t.name, t.color
            FROM document_tags dt
            JOIN tags t ON t.id = dt.tag_id
            WHERE dt.document_id = ?
            ORDER BY LOWER(t.name);
            """,
            (document_id,),
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def set_tags_for_document(self, document_id: int, tag_names: Sequence[str]) -> None:
        """
        Replace the tag set for a document with the given names.
        Behaviour mirrors set_tags_for_page.
        """
        # Normalise + dedupe (case-insensitive)
        clean_names: list[str] = []
        seen: set[str] = set()
        for name in tag_names:
            name = name.strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            clean_names.append(name)

        with self.conn:
            cur = self.conn.cursor()

            # Ensure the document exists
            exists = cur.execute(
                "SELECT 1 FROM project_documents WHERE id = ?;", (document_id,)
            ).fetchone()
            if not exists:
                raise sqlite.IntegrityError(f"Unknown document id {document_id}")

            if not clean_names:
                cur.execute(
                    "DELETE FROM document_tags WHERE document_id = ?;",
                    (document_id,),
                )
                return

            # For each tag name, reuse existing tag (case-insensitive) or create new
            final_tag_names: list[str] = []
            for name in clean_names:
                existing = cur.execute(
                    "SELECT name FROM tags WHERE LOWER(name) = LOWER(?);", (name,)
                ).fetchone()
                if existing:
                    final_tag_names.append(existing["name"])
                else:
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
                """,  # nosec
                tuple(final_tag_names),
            ).fetchall()
            ids_by_name = {r["name"]: r["id"] for r in rows}

            # Reset document_tags for this document
            cur.execute(
                "DELETE FROM document_tags WHERE document_id = ?;",
                (document_id,),
            )
            for name in final_tag_names:
                tag_id = ids_by_name.get(name)
                if tag_id is not None:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO document_tags(document_id, tag_id)
                        VALUES (?, ?);
                        """,
                        (document_id, tag_id),
                    )

    def documents_by_date(self) -> Dict[_dt.date, int]:
        """
        Return a mapping of date -> number of documents uploaded on that date.

        The keys are datetime.date objects derived from the
        project_documents.uploaded_at column, which is stored as a
        YYYY-MM-DD ISO date string (or a timestamp whose leading part
        is that date).
        """
        cur = self.conn.cursor()
        try:
            rows = cur.execute(
                """
                SELECT uploaded_at AS date_iso,
                       COUNT(*)     AS c
                FROM project_documents
                WHERE uploaded_at IS NOT NULL
                  AND uploaded_at != ''
                GROUP BY uploaded_at
                ORDER BY uploaded_at;
                """
            ).fetchall()
        except Exception:
            # Older DBs without project_documents/uploaded_at → no document stats
            return {}

        result: Dict[_dt.date, int] = {}
        for r in rows:
            date_iso = r["date_iso"]
            if not date_iso:
                continue

            # If uploaded_at ever contains a full timestamp, only use
            # the leading date portion.
            date_part = str(date_iso).split(" ", 1)[0][:10]
            try:
                d = _dt.date.fromisoformat(date_part)
            except Exception:  # nosec B112
                continue

            result[d] = int(r["c"])

        return result

    def todays_documents(self, date_iso: str) -> list[tuple[int, str, str | None, str]]:
        """
        Return today's documents as
        (doc_id, file_name, project_name, uploaded_at).
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT d.id            AS doc_id,
                   d.file_name     AS file_name,
                   p.name          AS project_name
            FROM project_documents AS d
            LEFT JOIN projects     AS p ON p.id = d.project_id
            WHERE d.uploaded_at LIKE ?
            ORDER BY d.uploaded_at DESC, LOWER(d.file_name);
            """,
            (f"%{date_iso}%",),
        ).fetchall()

        return [(r["doc_id"], r["file_name"], r["project_name"]) for r in rows]

    def get_documents_for_tag(self, tag_name: str) -> list[tuple[int, str, str]]:
        """
        Return (document_id, project_name, file_name) for documents with a given tag.
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT d.id AS doc_id,
                   p.name AS project_name,
                   d.file_name
            FROM project_documents AS d
            JOIN document_tags AS dt ON dt.document_id = d.id
            JOIN tags AS t ON t.id = dt.tag_id
            LEFT JOIN projects AS p ON p.id = d.project_id
            WHERE LOWER(t.name) = LOWER(?)
            ORDER BY LOWER(d.file_name);
            """,
            (tag_name,),
        ).fetchall()
        return [(r["doc_id"], r["project_name"], r["file_name"]) for r in rows]

    # ------------------------- Billing settings ------------------------#

    def get_project_billing(self, project_id: int) -> ProjectBillingRow | None:
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT
                project_id,
                hourly_rate_cents,
                currency,
                tax_label,
                tax_rate_percent,
                client_name,
                client_company,
                client_address,
                client_email
            FROM project_billing
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        if not row:
            return None
        return (
            row["project_id"],
            row["hourly_rate_cents"],
            row["currency"],
            row["tax_label"],
            row["tax_rate_percent"],
            row["client_name"],
            row["client_company"],
            row["client_address"],
            row["client_email"],
        )

    def upsert_project_billing(
        self,
        project_id: int,
        hourly_rate_cents: int,
        currency: str,
        tax_label: str | None,
        tax_rate_percent: float | None,
        client_name: str | None,
        client_company: str | None,
        client_address: str | None,
        client_email: str | None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO project_billing (
                    project_id,
                    hourly_rate_cents,
                    currency,
                    tax_label,
                    tax_rate_percent,
                    client_name,
                    client_company,
                    client_address,
                    client_email
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    hourly_rate_cents = excluded.hourly_rate_cents,
                    currency          = excluded.currency,
                    tax_label         = excluded.tax_label,
                    tax_rate_percent  = excluded.tax_rate_percent,
                    client_name       = excluded.client_name,
                    client_company    = excluded.client_company,
                    client_address    = excluded.client_address,
                    client_email      = excluded.client_email;
                """,
                (
                    project_id,
                    hourly_rate_cents,
                    currency,
                    tax_label,
                    tax_rate_percent,
                    client_name,
                    client_company,
                    client_address,
                    client_email,
                ),
            )

    def list_client_companies(self) -> list[str]:
        """Return distinct client display names from project_billing."""
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT DISTINCT client_company
            FROM project_billing
            WHERE client_company IS NOT NULL
              AND TRIM(client_company) <> ''
            ORDER BY LOWER(client_company);
            """
        ).fetchall()
        return [r["client_company"] for r in rows]

    def get_client_by_company(
        self, client_company: str
    ) -> tuple[str | None, str | None, str | None, str | None] | None:
        """
        Return (contact_name, client_display_name, address, email)
        for a given client display name, based on the most recent project using it.
        """
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT client_name, client_company, client_address, client_email
            FROM project_billing
            WHERE client_company = ?
              AND client_company IS NOT NULL
              AND TRIM(client_company) <> ''
            ORDER BY project_id DESC
            LIMIT 1
            """,
            (client_company,),
        ).fetchone()
        if not row:
            return None
        return (
            row["client_name"],
            row["client_company"],
            row["client_address"],
            row["client_email"],
        )

    # ------------------------- Company profile ------------------------#

    def get_company_profile(self) -> CompanyProfileRow | None:
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT name, address, phone, email, tax_id, payment_details, logo
            FROM company_profile
            WHERE id = 1
            """
        ).fetchone()
        if not row:
            return None
        return (
            row["name"],
            row["address"],
            row["phone"],
            row["email"],
            row["tax_id"],
            row["payment_details"],
            row["logo"],
        )

    def save_company_profile(
        self,
        name: str | None,
        address: str | None,
        phone: str | None,
        email: str | None,
        tax_id: str | None,
        payment_details: str | None,
        logo: bytes | None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO company_profile (id, name, address, phone, email, tax_id, payment_details, logo)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name    = excluded.name,
                    address = excluded.address,
                    phone   = excluded.phone,
                    email   = excluded.email,
                    tax_id  = excluded.tax_id,
                    payment_details = excluded.payment_details,
                    logo    = excluded.logo;
                """,
                (
                    name,
                    address,
                    phone,
                    email,
                    tax_id,
                    payment_details,
                    Binary(logo) if logo else None,
                ),
            )

    # ------------------------- Invoices -------------------------------#

    def create_invoice(
        self,
        project_id: int,
        invoice_number: str,
        issue_date: str,
        due_date: str | None,
        currency: str,
        tax_label: str | None,
        tax_rate_percent: float | None,
        detail_mode: str,  # 'detailed' or 'summary'
        line_items: list[tuple[str, float, int]],  # (description, hours, rate_cents)
        time_log_ids: list[int],
    ) -> int:
        """
        Create invoice + line items + link time logs.
        Returns invoice ID.
        """
        if line_items:
            first_rate_cents = line_items[0][2]
        else:
            first_rate_cents = 0

        total_hours = sum(hours for _desc, hours, _rate in line_items)
        subtotal_cents = int(round(total_hours * first_rate_cents))
        tax_cents = int(round(subtotal_cents * (tax_rate_percent or 0) / 100.0))
        total_cents = subtotal_cents + tax_cents

        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO invoices (
                    project_id,
                    invoice_number,
                    issue_date,
                    due_date,
                    currency,
                    tax_label,
                    tax_rate_percent,
                    subtotal_cents,
                    tax_cents,
                    total_cents,
                    detail_mode
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    invoice_number,
                    issue_date,
                    due_date,
                    currency,
                    tax_label,
                    tax_rate_percent,
                    subtotal_cents,
                    tax_cents,
                    total_cents,
                    detail_mode,
                ),
            )
            invoice_id = cur.lastrowid

            # Line items
            for desc, hours, rate_cents in line_items:
                amount_cents = int(round(hours * rate_cents))
                cur.execute(
                    """
                    INSERT INTO invoice_line_items (
                        invoice_id, description, hours, rate_cents, amount_cents
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (invoice_id, desc, hours, rate_cents, amount_cents),
                )

            # Link time logs
            for tl_id in time_log_ids:
                cur.execute(
                    "INSERT INTO invoice_time_log (invoice_id, time_log_id) VALUES (?, ?)",
                    (invoice_id, tl_id),
                )

            return invoice_id

    def get_invoice_count_by_project_id_and_year(
        self, project_id: int, year: str
    ) -> None:
        with self.conn:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM invoices WHERE project_id = ? AND issue_date LIKE ?",
                (project_id, year),
            ).fetchone()
        return row["c"]

    def get_all_invoices(self, project_id: int | None = None) -> None:
        with self.conn:
            if project_id is None:
                rows = self.conn.execute(
                    """
                    SELECT
                        i.id,
                        i.project_id,
                        p.name AS project_name,
                        i.invoice_number,
                        i.issue_date,
                        i.due_date,
                        i.currency,
                        i.tax_label,
                        i.tax_rate_percent,
                        i.subtotal_cents,
                        i.tax_cents,
                        i.total_cents,
                        i.paid_at,
                        i.payment_note
                    FROM invoices AS i
                    LEFT JOIN projects AS p ON p.id = i.project_id
                    ORDER BY i.issue_date DESC, i.invoice_number COLLATE NOCASE;
                    """
                ).fetchall()
            else:
                rows = self.conn.execute(
                    """
                    SELECT
                        i.id,
                        i.project_id,
                        p.name AS project_name,
                        i.invoice_number,
                        i.issue_date,
                        i.due_date,
                        i.currency,
                        i.tax_label,
                        i.tax_rate_percent,
                        i.subtotal_cents,
                        i.tax_cents,
                        i.total_cents,
                        i.paid_at,
                        i.payment_note
                    FROM invoices AS i
                    LEFT JOIN projects AS p ON p.id = i.project_id
                    WHERE i.project_id = ?
                    ORDER BY i.issue_date DESC, i.invoice_number COLLATE NOCASE;
                    """,
                    (project_id,),
                ).fetchall()
        return rows

    def _validate_invoice_field(self, field: str) -> str:
        if field not in self._INVOICE_COLUMN_ALLOWLIST:
            raise ValueError(f"Invalid invoice field name: {field!r}")
        return field

    def get_invoice_field_by_id(self, invoice_id: int, field: str) -> None:
        field = self._validate_invoice_field(field)

        with self.conn:
            row = self.conn.execute(
                f"SELECT {field} FROM invoices WHERE id = ?",  # nosec B608
                (invoice_id,),
            ).fetchone()
        return row

    def set_invoice_field_by_id(
        self, invoice_id: int, field: str, value: str | None = None
    ) -> None:
        field = self._validate_invoice_field(field)

        with self.conn:
            self.conn.execute(
                f"UPDATE invoices SET {field} = ? WHERE id = ?",  # nosec B608
                (
                    value,
                    invoice_id,
                ),
            )

    def update_invoice_number(self, invoice_id: int, invoice_number: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE invoices SET invoice_number = ? WHERE id = ?",
                (invoice_number, invoice_id),
            )

    def set_invoice_document(self, invoice_id: int, document_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE invoices SET document_id = ? WHERE id = ?",
                (document_id, invoice_id),
            )

    def delete_invoice(self, invoice_id: int) -> None:
        """Delete an invoice.

        Related invoice line items and invoice ↔ time log links are removed via
        ON DELETE CASCADE.
        """
        with self.conn:
            self.conn.execute(
                "DELETE FROM invoices WHERE id = ?",
                (invoice_id,),
            )

    def time_logs_for_range(
        self,
        project_id: int,
        start_date_iso: str,
        end_date_iso: str,
    ) -> list[TimeLogRow]:
        """
        Return raw time log rows for a project/date range.

        Shape matches time_log_for_date: TimeLogRow.
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT
                t.id,
                t.page_date,
                t.project_id,
                p.name AS project_name,
                t.activity_id,
                a.name AS activity_name,
                t.minutes,
                t.note,
                t.created_at AS created_at
            FROM time_log t
            JOIN projects  p ON p.id = t.project_id
            JOIN activities a ON a.id = t.activity_id
            WHERE t.project_id = ?
              AND t.page_date BETWEEN ? AND ?
            ORDER BY t.page_date, LOWER(a.name), t.id;
            """,
            (project_id, start_date_iso, end_date_iso),
        ).fetchall()

        result: list[TimeLogRow] = []
        for r in rows:
            result.append(
                (
                    r["id"],
                    r["page_date"],
                    r["project_id"],
                    r["project_name"],
                    r["activity_id"],
                    r["activity_name"],
                    r["minutes"],
                    r["note"],
                    r["created_at"],
                )
            )
        return result
