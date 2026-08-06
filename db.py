"""
db.py — the system's local memory (a single SQLite file on the Mac).

Three things live here:
  * users    — who can log in, and their role (Super Admin / Spa Manager / Team Member)
  * clients  — one row per caller, keyed by phone number (the client's "ID")
  * messages — after-hours call transcripts, each tied to a client, with a
               "responded" status the team can flip in the dashboard.

The Obsidian vault holds the readable per-client "brain"; this database holds
the structured state the dashboard needs (statuses, roles, who responded, etc.).
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.environ.get("DB_PATH", "data/app.db"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                email       TEXT UNIQUE NOT NULL,
                name        TEXT,
                role        TEXT NOT NULL,
                active      INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS clients (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                phone       TEXT UNIQUE NOT NULL,
                name        TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id     INTEGER NOT NULL REFERENCES clients(id),
                created_at    TEXT NOT NULL,
                channel       TEXT NOT NULL DEFAULT 'after_hours_call',
                transcript    TEXT,
                summary       TEXT,
                status        TEXT NOT NULL DEFAULT 'new',   -- 'new' or 'responded'
                responded_by  TEXT,
                responded_at  TEXT,
                obsidian_file TEXT,
                ghl_call_id   TEXT UNIQUE
            );
            """
        )
        # Lightweight migrations: add columns that newer versions expect, so an
        # existing database picks them up without being rebuilt.
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
        if "duration" not in existing:
            conn.execute("ALTER TABLE messages ADD COLUMN duration TEXT")


# --- Users -------------------------------------------------------------------
def get_user_by_email(email: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower(),)
        ).fetchone()
        return dict(row) if row else None


def upsert_user_on_login(email: str, name: str, role_if_new: str) -> dict:
    """Create the user on first login (with role_if_new); otherwise return them."""
    email = email.lower()
    existing = get_user_by_email(email)
    if existing:
        # Keep their existing role; just refresh the display name.
        with _connect() as conn:
            conn.execute("UPDATE users SET name = ? WHERE email = ?", (name, email))
        existing["name"] = name
        return existing

    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (email, name, role, active, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (email, name, role_if_new, datetime.now().isoformat(timespec="seconds")),
        )
    return get_user_by_email(email)


def list_users() -> list[dict]:
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM users ORDER BY role, email"
        ).fetchall()]


def set_user_role(email: str, role: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE users SET role = ? WHERE email = ?", (role, email.lower()))


def set_user_active(email: str, active: bool) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET active = ? WHERE email = ?",
            (1 if active else 0, email.lower()),
        )


# --- Clients (keyed by phone number) ----------------------------------------
def get_or_create_client(phone: str, name: Optional[str] = None) -> dict:
    phone = (phone or "unknown").strip()
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM clients WHERE phone = ?", (phone,)
        ).fetchone()
        if row:
            # Fill in a name if we didn't have one before.
            if name and not row["name"]:
                conn.execute(
                    "UPDATE clients SET name = ?, updated_at = ? WHERE id = ?",
                    (name, now, row["id"]),
                )
            return dict(row)
        cur = conn.execute(
            "INSERT INTO clients (phone, name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (phone, name, now, now),
        )
        return {"id": int(cur.lastrowid), "phone": phone, "name": name}


# --- Messages ----------------------------------------------------------------
def add_message(
    client_id: int,
    transcript: str,
    summary: Optional[str] = None,
    duration: Optional[str] = None,
    channel: str = "after_hours_call",
    obsidian_file: Optional[str] = None,
    ghl_call_id: Optional[str] = None,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO messages "
            "(client_id, created_at, channel, transcript, summary, duration, "
            " status, obsidian_file, ghl_call_id) "
            "VALUES (?, ?, ?, ?, ?, ?, 'new', ?, ?)",
            (
                client_id,
                datetime.now().isoformat(timespec="seconds"),
                channel,
                transcript,
                summary,
                duration,
                obsidian_file,
                ghl_call_id,
            ),
        )
        return int(cur.lastrowid)


def list_messages(status: Optional[str] = None) -> list[dict]:
    """Messages joined with their client, newest first. Optional status filter."""
    query = (
        "SELECT m.*, c.phone AS client_phone, c.name AS client_name "
        "FROM messages m JOIN clients c ON c.id = m.client_id "
    )
    params: tuple = ()
    if status:
        query += "WHERE m.status = ? "
        params = (status,)
    query += "ORDER BY m.id DESC"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def count_new_messages() -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM messages WHERE status = 'new'"
        ).fetchone()[0]


def mark_message_responded(message_id: int, responded_by: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE messages SET status = 'responded', responded_by = ?, "
            "responded_at = ? WHERE id = ?",
            (responded_by, datetime.now().isoformat(timespec="seconds"), message_id),
        )
