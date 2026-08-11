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
from datetime import datetime, timedelta
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

            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       TEXT,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS charlie_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT NOT NULL,
                user_email  TEXT NOT NULL,
                role        TEXT NOT NULL,   -- 'user' or 'charlie'
                content     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS charlie_actions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT NOT NULL,
                user_email  TEXT NOT NULL,
                channel     TEXT NOT NULL,   -- 'email' or 'sms'
                recipient   TEXT,            -- email address or phone
                subject     TEXT,
                body        TEXT NOT NULL,
                contact_id  TEXT,            -- GHL contact id (sms), if known
                status      TEXT NOT NULL DEFAULT 'pending',  -- pending|sent|cancelled|failed
                result      TEXT,
                sent_at     TEXT
            );

            CREATE TABLE IF NOT EXISTS inbox_convos (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id    TEXT,
                contact_name  TEXT,
                phone         TEXT,
                email         TEXT,
                channel       TEXT NOT NULL DEFAULT 'sms',
                status        TEXT NOT NULL DEFAULT 'open',   -- open | closed
                attention     TEXT NOT NULL DEFAULT 'none',   -- none | draft | handoff
                draft         TEXT,           -- Charlie's suggested reply (attention=draft)
                handoff_note  TEXT,           -- what Charlie is unsure about (attention=handoff)
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL,
                closed_by     TEXT,
                closed_at     TEXT,
                close_reason  TEXT
            );

            CREATE TABLE IF NOT EXISTS inbox_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                convo_id    INTEGER NOT NULL REFERENCES inbox_convos(id),
                created_at  TEXT NOT NULL,
                role        TEXT NOT NULL,   -- contact | charlie | team | system
                body        TEXT NOT NULL,
                via         TEXT             -- sms | email | note
            );

            CREATE TABLE IF NOT EXISTS meetings (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                granola_id     TEXT UNIQUE NOT NULL,
                category       TEXT NOT NULL,   -- 'client' or 'team'
                title          TEXT,
                meeting_date   TEXT,            -- ISO from Granola
                folder         TEXT,
                attendees      TEXT,            -- newline-separated
                summary        TEXT,
                transcript     TEXT,
                status         TEXT NOT NULL DEFAULT 'pending',
                                 -- client: pending|confirmed|dismissed ; team: filed
                captured_at    TEXT NOT NULL,
                client_contact_id TEXT,         -- GHL contact id, once confirmed
                client_name    TEXT,
                client_phone   TEXT,
                client_email   TEXT,
                obsidian_file  TEXT,
                ghl_note_id    TEXT,
                confirmed_by   TEXT,
                confirmed_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS appointments (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at     TEXT NOT NULL,
                created_by     TEXT,
                contact_name   TEXT NOT NULL,
                email          TEXT,
                phone          TEXT,
                appt_at        TEXT NOT NULL,   -- local ISO 'YYYY-MM-DDTHH:MM'
                type_key       TEXT NOT NULL,
                type_label     TEXT NOT NULL,
                workflow_id    TEXT,
                workflow_name  TEXT,
                ghl_contact_id TEXT,
                ghl_appointment_id TEXT,
                status         TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled|cancelled
                note           TEXT
            );
            """
        )
        # Lightweight migrations: add columns that newer versions expect, so an
        # existing database picks them up without being rebuilt.
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
        if "duration" not in existing:
            conn.execute("ALTER TABLE messages ADD COLUMN duration TEXT")
        user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        if user_cols and "password_hash" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        appt_cols = {row["name"] for row in conn.execute("PRAGMA table_info(appointments)")}
        if appt_cols and "ghl_appointment_id" not in appt_cols:
            conn.execute("ALTER TABLE appointments ADD COLUMN ghl_appointment_id TEXT")


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


def create_user(email: str, name: str, role: str,
                password_hash: Optional[str] = None, active: bool = True) -> dict:
    """Create a team member directly (from the Team page). Raises on duplicate email."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (email, name, role, active, created_at, password_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (email.lower(), name, role, 1 if active else 0,
             datetime.now().isoformat(timespec="seconds"), password_hash),
        )
    return get_user_by_email(email)


def set_user_password(email: str, password_hash: Optional[str]) -> None:
    """Set (or clear, with None) a user's password hash."""
    with _connect() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE email = ?",
                     (password_hash, email.lower()))


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


# --- Settings (small key/value store, e.g. reminder workflow mapping) --------
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row and row["value"] is not None else default


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, value, datetime.now().isoformat(timespec="seconds")),
        )


def delete_setting(key: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


# --- Appointment reminders ---------------------------------------------------
def add_appointment(
    contact_name: str,
    appt_at: str,
    type_key: str,
    type_label: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    workflow_id: Optional[str] = None,
    workflow_name: Optional[str] = None,
    ghl_contact_id: Optional[str] = None,
    ghl_appointment_id: Optional[str] = None,
    created_by: Optional[str] = None,
    note: Optional[str] = None,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO appointments "
            "(created_at, created_by, contact_name, email, phone, appt_at, "
            " type_key, type_label, workflow_id, workflow_name, ghl_contact_id, "
            " ghl_appointment_id, status, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                created_by, contact_name, email, phone, appt_at,
                type_key, type_label, workflow_id, workflow_name, ghl_contact_id,
                ghl_appointment_id, note,
            ),
        )
        return int(cur.lastrowid)


def list_appointments(status: Optional[str] = None, limit: int = 200) -> list[dict]:
    """Appointments, soonest upcoming first then past. Optional status filter."""
    query = "SELECT * FROM appointments "
    params: list = []
    if status:
        query += "WHERE status = ? "
        params.append(status)
    # Upcoming (appt_at >= now) ascending, then past descending.
    now = datetime.now().isoformat(timespec="minutes")
    query += (
        "ORDER BY CASE WHEN appt_at >= ? THEN 0 ELSE 1 END, "
        "CASE WHEN appt_at >= ? THEN appt_at END ASC, appt_at DESC LIMIT ?"
    )
    params.extend([now, now, limit])
    with _connect() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def list_upcoming_appointments(limit: int = 5) -> list[dict]:
    now = datetime.now().isoformat(timespec="minutes")
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM appointments WHERE status = 'scheduled' AND appt_at >= ? "
            "ORDER BY appt_at ASC LIMIT ?",
            (now, limit),
        ).fetchall()]


def count_upcoming_appointments() -> int:
    now = datetime.now().isoformat(timespec="minutes")
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM appointments WHERE status = 'scheduled' AND appt_at >= ?",
            (now,),
        ).fetchone()[0]


def cancel_appointment(appt_id: int) -> None:
    with _connect() as conn:
        conn.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (appt_id,))


def list_appointments_for(ghl_contact_id: Optional[str] = None,
                          email: Optional[str] = None,
                          phone: Optional[str] = None) -> list[dict]:
    """All appointments for one person (matched by GHL id, else email/phone)."""
    clauses, params = [], []
    if ghl_contact_id:
        clauses.append("ghl_contact_id = ?"); params.append(ghl_contact_id)
    if email:
        clauses.append("lower(email) = ?"); params.append(email.lower())
    if phone:
        clauses.append("phone = ?"); params.append(phone)
    if not clauses:
        return []
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM appointments WHERE {' OR '.join(clauses)} ORDER BY appt_at DESC",
            params,
        ).fetchall()]


def list_client_summaries() -> list[dict]:
    """One row per distinct person we've scheduled, for the Clients list.

    Grouped by GHL contact id when known, else email, else phone. Returns the
    most recent name/contact info plus appointment counts and next/last dates.
    """
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM appointments ORDER BY created_at DESC"
        ).fetchall()]
    now = datetime.now().isoformat(timespec="minutes")
    groups: dict[str, dict] = {}
    for a in rows:
        key = a.get("ghl_contact_id") or (a.get("email") or "").lower() or a.get("phone") or f"row{a['id']}"
        g = groups.get(key)
        if not g:
            g = groups[key] = {
                "key": key,
                "contact_id": a.get("ghl_contact_id") or "",
                "name": a.get("contact_name"),
                "email": a.get("email") or "",
                "phone": a.get("phone") or "",
                "total": 0, "upcoming": 0,
                "next_appt": None, "last_appt": None,
            }
        # First-seen (newest created) wins for display fields already set above.
        g["contact_id"] = g["contact_id"] or (a.get("ghl_contact_id") or "")
        g["email"] = g["email"] or (a.get("email") or "")
        g["phone"] = g["phone"] or (a.get("phone") or "")
        if a.get("status") != "cancelled":
            g["total"] += 1
            at = a.get("appt_at")
            if at and at >= now:
                g["upcoming"] += 1
                if g["next_appt"] is None or at < g["next_appt"]:
                    g["next_appt"] = at
            if g["last_appt"] is None or (at and at > g["last_appt"]):
                g["last_appt"] = at
    return sorted(groups.values(),
                  key=lambda g: g["next_appt"] or g["last_appt"] or "", reverse=True)


# --- Charlie's Inbox (conversations) -----------------------------------------
def add_inbox_message(convo_id: int, role: str, body: str,
                      via: Optional[str] = None) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO inbox_messages (convo_id, created_at, role, body, via) "
            "VALUES (?, ?, ?, ?, ?)",
            (convo_id, datetime.now().isoformat(timespec="seconds"), role, body, via),
        )
        conn.execute("UPDATE inbox_convos SET updated_at = ? WHERE id = ?",
                     (datetime.now().isoformat(timespec="seconds"), convo_id))
        return int(cur.lastrowid)


def get_open_convo_by_phone(phone: str) -> Optional[dict]:
    if not phone:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM inbox_convos WHERE phone = ? AND status = 'open' "
            "ORDER BY id DESC LIMIT 1", (phone,),
        ).fetchone()
        return dict(row) if row else None


def get_or_create_convo(phone: Optional[str] = None, contact_id: Optional[str] = None,
                        contact_name: Optional[str] = None, email: Optional[str] = None,
                        channel: str = "sms") -> dict:
    """Find the open conversation for this phone, or start a new one."""
    existing = get_open_convo_by_phone(phone) if phone else None
    if existing:
        # Backfill contact identity if we learn it later.
        with _connect() as conn:
            conn.execute(
                "UPDATE inbox_convos SET "
                "contact_id = COALESCE(NULLIF(?, ''), contact_id), "
                "contact_name = COALESCE(NULLIF(?, ''), contact_name), "
                "email = COALESCE(NULLIF(?, ''), email) WHERE id = ?",
                (contact_id or "", contact_name or "", email or "", existing["id"]),
            )
        return get_convo(existing["id"])
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO inbox_convos (contact_id, contact_name, phone, email, channel, "
            " status, attention, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'open', 'none', ?, ?)",
            (contact_id, contact_name, phone, email, channel, now, now),
        )
        new_id = int(cur.lastrowid)
    return get_convo(new_id)


def get_convo(convo_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM inbox_convos WHERE id = ?", (convo_id,)).fetchone()
        return dict(row) if row else None


def list_convo_messages(convo_id: int) -> list[dict]:
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM inbox_messages WHERE convo_id = ? ORDER BY id ASC",
            (convo_id,),
        ).fetchall()]


def set_convo_attention(convo_id: int, attention: str, draft: Optional[str] = None,
                        handoff_note: Optional[str] = None) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE inbox_convos SET attention = ?, draft = ?, handoff_note = ?, "
            "updated_at = ? WHERE id = ?",
            (attention, draft, handoff_note,
             datetime.now().isoformat(timespec="seconds"), convo_id),
        )


def set_convo_contact_id(convo_id: int, contact_id: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE inbox_convos SET contact_id = ? WHERE id = ?",
                     (contact_id, convo_id))


def close_convo(convo_id: int, by: str, reason: str = "team handling") -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "UPDATE inbox_convos SET status = 'closed', attention = 'none', "
            "closed_by = ?, closed_at = ?, close_reason = ?, updated_at = ? WHERE id = ?",
            (by, now, reason, now, convo_id),
        )


def list_inbox(status: str = "open", limit: int = 100) -> list[dict]:
    """Conversations for the inbox (newest activity first), each with its messages."""
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM inbox_convos WHERE status = ? "
            "ORDER BY updated_at DESC, id DESC LIMIT ?", (status, limit),
        ).fetchall()]
    for c in rows:
        c["messages"] = list_convo_messages(c["id"])
    return rows


def count_inbox_attention() -> int:
    """Open conversations that need a team member (draft to send or hand-off)."""
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM inbox_convos WHERE status = 'open' AND attention != 'none'"
        ).fetchone()[0]


# --- Granola meeting notes ---------------------------------------------------
def upsert_meeting(granola_id: str, category: str, title: str,
                   meeting_date: Optional[str] = None, folder: Optional[str] = None,
                   attendees: Optional[str] = None, summary: Optional[str] = None,
                   transcript: Optional[str] = None) -> dict:
    """
    Insert a pulled Granola meeting into the queue if we haven't seen it. Returns
    {"id", "new"}. Existing rows are refreshed with any newly-available summary/
    transcript but keep their status (so a confirmed note stays confirmed).
    """
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM meetings WHERE granola_id = ?", (granola_id,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE meetings SET title = ?, meeting_date = ?, folder = ?, "
                "attendees = ?, "
                "summary = COALESCE(NULLIF(?, ''), summary), "
                "transcript = COALESCE(NULLIF(?, ''), transcript) "
                "WHERE id = ?",
                (title, meeting_date, folder, attendees, summary or "",
                 transcript or "", row["id"]),
            )
            return {"id": int(row["id"]), "new": False}
        status = "filed" if category == "team" else "pending"
        cur = conn.execute(
            "INSERT INTO meetings (granola_id, category, title, meeting_date, folder, "
            " attendees, summary, transcript, status, captured_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (granola_id, category, title, meeting_date, folder, attendees,
             summary, transcript, status, now),
        )
        return {"id": int(cur.lastrowid), "new": True}


def list_meetings(category: Optional[str] = None, status: Optional[str] = None,
                  limit: int = 200) -> list[dict]:
    """Meetings, newest by meeting date first. Optional category/status filter."""
    query = "SELECT * FROM meetings "
    clauses, params = [], []
    if category:
        clauses.append("category = ?"); params.append(category)
    if status:
        clauses.append("status = ?"); params.append(status)
    if clauses:
        query += "WHERE " + " AND ".join(clauses) + " "
    query += "ORDER BY COALESCE(meeting_date, captured_at) DESC, id DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_meeting(meeting_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        return dict(row) if row else None


def count_pending_meetings() -> int:
    """Client consults still waiting to be confirmed (for the sidebar badge)."""
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM meetings WHERE category = 'client' AND status = 'pending'"
        ).fetchone()[0]


def confirm_meeting(meeting_id: int, contact_id: str, client_name: str,
                    confirmed_by: str, client_phone: Optional[str] = None,
                    client_email: Optional[str] = None,
                    obsidian_file: Optional[str] = None,
                    ghl_note_id: Optional[str] = None) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE meetings SET status = 'confirmed', client_contact_id = ?, "
            "client_name = ?, client_phone = ?, client_email = ?, obsidian_file = ?, "
            "ghl_note_id = ?, confirmed_by = ?, confirmed_at = ? WHERE id = ?",
            (contact_id, client_name, client_phone, client_email, obsidian_file,
             ghl_note_id, confirmed_by, datetime.now().isoformat(timespec="seconds"),
             meeting_id),
        )


def dismiss_meeting(meeting_id: int, by: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE meetings SET status = 'dismissed', confirmed_by = ?, confirmed_at = ? "
            "WHERE id = ?",
            (by, datetime.now().isoformat(timespec="seconds"), meeting_id),
        )


def set_meeting_obsidian_file(meeting_id: int, path: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE meetings SET obsidian_file = ? WHERE id = ?", (path, meeting_id))


# --- Charlie chat history -----------------------------------------------------
def add_charlie_message(user_email: str, role: str, content: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO charlie_messages (created_at, user_email, role, content) "
            "VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), user_email.lower(), role, content),
        )
        return int(cur.lastrowid)


def list_charlie_messages(user_email: str, limit: int = 40) -> list[dict]:
    """This user's most recent Charlie turns, oldest-first for display."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM charlie_messages WHERE user_email = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_email.lower(), limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def clear_charlie_messages(user_email: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM charlie_messages WHERE user_email = ?", (user_email.lower(),))


def add_charlie_action(user_email: str, channel: str, recipient: str, body: str,
                       subject: Optional[str] = None, contact_id: Optional[str] = None) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO charlie_actions "
            "(created_at, user_email, channel, recipient, subject, body, contact_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
            (datetime.now().isoformat(timespec="seconds"), user_email.lower(),
             channel, recipient, subject, body, contact_id),
        )
        return int(cur.lastrowid)


def get_charlie_action(action_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM charlie_actions WHERE id = ?", (action_id,)).fetchone()
        return dict(row) if row else None


def latest_pending_action(user_email: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM charlie_actions WHERE user_email = ? AND status = 'pending' "
            "ORDER BY id DESC LIMIT 1",
            (user_email.lower(),),
        ).fetchone()
        return dict(row) if row else None


def list_charlie_actions(limit: int = 100) -> list[dict]:
    """Resolved Charlie sends (sent/failed/cancelled), newest first — the send log."""
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM charlie_actions WHERE status != 'pending' "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()]


def set_charlie_action_status(action_id: int, status: str, result: Optional[str] = None) -> None:
    sent_at = datetime.now().isoformat(timespec="seconds") if status == "sent" else None
    with _connect() as conn:
        conn.execute(
            "UPDATE charlie_actions SET status = ?, result = ?, sent_at = ? WHERE id = ?",
            (status, result, sent_at, action_id),
        )


def list_messages_for_phone(phone: str) -> list[dict]:
    """After-hours call messages for a given phone number, newest first."""
    if not phone:
        return []
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT m.*, c.phone AS client_phone, c.name AS client_name "
            "FROM messages m JOIN clients c ON c.id = m.client_id "
            "WHERE c.phone = ? ORDER BY m.id DESC",
            (phone,),
        ).fetchall()]


# --- Dashboard metrics (for the Overview charts) -----------------------------
def status_breakdown() -> dict:
    """How many messages are still new vs. responded (all-time)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) c FROM messages GROUP BY status"
        ).fetchall()
    counts = {r["status"]: r["c"] for r in rows}
    new = counts.get("new", 0)
    responded = counts.get("responded", 0)
    return {"new": new, "responded": responded, "total": new + responded}


def messages_by_day(days: int = 14) -> list[dict]:
    """
    A continuous per-day series for the last `days` days (gap-filled with zeros),
    oldest first. Each entry: day (ISO), label (day-of-month), weekday, total,
    responded, new. Drives the Overview activity chart.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT date(created_at) d, COUNT(*) total, "
            "SUM(CASE WHEN status = 'responded' THEN 1 ELSE 0 END) responded "
            "FROM messages GROUP BY date(created_at)"
        ).fetchall()
    by_day = {r["d"]: (r["total"], r["responded"] or 0) for r in rows}
    today = datetime.now().date()
    out: list[dict] = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        total, responded = by_day.get(d.isoformat(), (0, 0))
        out.append({
            "day": d.isoformat(),
            "label": d.strftime("%-d"),
            "weekday": d.strftime("%a"),
            "total": total,
            "responded": responded,
            "new": total - responded,
        })
    return out
