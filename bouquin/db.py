from __future__ import annotations

import csv
import html
import json
import os

from dataclasses import dataclass
from pathlib import Path
from sqlcipher3 import dbapi2 as sqlite
from typing import List, Sequence, Tuple

Entry = Tuple[str, str]


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
        self.conn.row_factory = sqlite.Row
        cur = self.conn.cursor()
        cur.execute(f"PRAGMA key = '{self.cfg.key}';")
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

    def rekey(self, new_key: str) -> None:
        """
        Change the SQLCipher passphrase in-place, then reopen the connection
        with the new key to verify.
        """
        if self.conn is None:
            raise RuntimeError("Database is not connected")
        cur = self.conn.cursor()
        # Change the encryption key of the currently open database
        cur.execute(f"PRAGMA rekey = '{new_key}';")
        self.conn.commit()

        # Close and reopen with the new key to verify and restore PRAGMAs
        self.conn.close()
        self.conn = None
        self.cfg.key = new_key
        if not self.connect():
            raise sqlite.Error("Re-open failed after rekey")

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

    def search_entries(self, text: str) -> list[str]:
        cur = self.conn.cursor()
        pattern = f"%{text}%"
        return cur.execute(
            "SELECT * FROM entries WHERE TRIM(content) LIKE ?", (pattern,)
        ).fetchall()

    def dates_with_content(self) -> list[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT date FROM entries WHERE TRIM(content) <> '';")
        return [r[0] for r in cur.fetchall()]

    def get_all_entries(self) -> List[Entry]:
        cur = self.conn.cursor()
        rows = cur.execute("SELECT date, content FROM entries ORDER BY date").fetchall()
        return [(row["date"], row["content"]) for row in rows]

    def export_json(
        self, entries: Sequence[Entry], file_path: str, pretty: bool = True
    ) -> None:
        data = [{"date": d, "content": c} for d, c in entries]
        with open(file_path, "w", encoding="utf-8") as f:
            if pretty:
                json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    def export_csv(self, entries: Sequence[Entry], file_path: str) -> None:
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
        strip_html: bool = True,
    ) -> None:
        import re, html as _html

        # Precompiled patterns
        STYLE_SCRIPT_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
        COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
        BR_RE = re.compile(r"(?i)<br\\s*/?>")
        BLOCK_END_RE = re.compile(r"(?i)</(p|div|section|article|li|h[1-6])\\s*>")
        TAG_RE = re.compile(r"<[^>]+>")
        WS_ENDS_RE = re.compile(r"[ \\t]+\\n")
        MULTINEWLINE_RE = re.compile(r"\\n{3,}")

        def _strip(s: str) -> str:
            # 1) Remove <style> and <script> blocks *including their contents*
            s = STYLE_SCRIPT_RE.sub("", s)
            # 2) Remove HTML comments
            s = COMMENT_RE.sub("", s)
            # 3) Turn some block-ish boundaries into newlines before removing tags
            s = BR_RE.sub("\n", s)
            s = BLOCK_END_RE.sub("\n", s)
            # 4) Drop remaining tags
            s = TAG_RE.sub("", s)
            # 5) Unescape entities (&nbsp; etc.)
            s = _html.unescape(s)
            # 6) Tidy whitespace
            s = WS_ENDS_RE.sub("\n", s)
            s = MULTINEWLINE_RE.sub("\n\n", s)
            return s.strip()

        with open(file_path, "w", encoding="utf-8") as f:
            for i, (d, c) in enumerate(entries):
                body = _strip(c) if strip_html else c
                f.write(f"{d}\n{body}\n")
                if i < len(entries) - 1:
                    f.write(separator)

    def export_html(
        self, entries: Sequence[Entry], file_path: str, title: str = "Entries export"
    ) -> None:
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

    def export_by_extension(self, file_path: str) -> None:
        entries = self.get_all_entries()
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".json":
            self.export_json(entries, file_path)
        elif ext == ".csv":
            self.export_csv(entries, file_path)
        elif ext == ".txt":
            self.export_txt(entries, file_path)
        elif ext in {".html", ".htm"}:
            self.export_html(entries, file_path)
        else:
            raise ValueError(f"Unsupported extension: {ext}")

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None
