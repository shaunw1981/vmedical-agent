"""
notes_db.py — where the notes are actually stored.

This uses SQLite, a tiny database that lives in a single file on the Mac Mini
(by default: ./data/notes.db). Nothing leaves the machine. There is no cloud
database and no external server involved in storage.

If you ever want a backup, you literally just copy that one .db file.
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

# Where the database file lives. Configurable via the DB_PATH setting in .env.
DB_PATH = Path(os.environ.get("DB_PATH", "data/notes.db"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the notes table the first time the app runs."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at    TEXT NOT NULL,
                note_type     TEXT NOT NULL,   -- 'voicemail' or 'appointment'
                caller_name   TEXT,
                caller_phone  TEXT,
                raw_text      TEXT,            -- exactly what came in
                clean_text    TEXT,            -- tidied version (if enabled)
                source        TEXT             -- e.g. 'gohighlevel', 'manual'
            )
            """
        )


def add_note(
    note_type: str,
    raw_text: str,
    caller_name: Optional[str] = None,
    caller_phone: Optional[str] = None,
    clean_text: Optional[str] = None,
    source: str = "manual",
) -> int:
    """Save one note and return its id."""
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO notes
              (created_at, note_type, caller_name, caller_phone,
               raw_text, clean_text, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                note_type,
                caller_name,
                caller_phone,
                raw_text,
                clean_text,
                source,
            ),
        )
        return int(cur.lastrowid)


def list_notes(limit: int = 200) -> list[dict]:
    """Return the most recent notes, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
