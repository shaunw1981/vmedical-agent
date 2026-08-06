"""
vmedical-agent — a small notes app that runs on the Mac Mini at the spa.

What it does:
  * Receives voicemail notes and appointment notes (from GoHighLevel, or added
    by hand) and stores them LOCALLY on this Mac in a single database file.
  * Shows staff a simple web page to read the notes, at an address on the
    spa's own network (e.g. http://localhost:8000).

What it does NOT do:
  * It does not send your stored notes to any cloud. Storage is 100% local.
  * The ONE exception is optional "AI tidy-up" (off by default): if you turn it
    on, the *text of a voicemail* is sent to Anthropic to be rewritten into a
    clean note. Leave it off to keep everything fully local. See .env.example.

You normally don't run this by hand — the Mac Mini setup starts it
automatically. See SETUP-MACMINI.md.
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import notes_db
import obsidian

load_dotenv()

# --- Optional AI tidy-up (OFF by default to keep everything local) -----------
# Set AI_CLEANUP=on in .env to have Claude rewrite messy voicemail transcripts
# into clean notes. When on, that text is sent to Anthropic. When off, notes are
# stored exactly as received and nothing leaves the Mac.
AI_CLEANUP = os.environ.get("AI_CLEANUP", "off").lower() == "on"
MODEL = os.environ.get("MODEL", "claude-sonnet-5")

_anthropic_client = None
if AI_CLEANUP:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        from anthropic import Anthropic

        _anthropic_client = Anthropic(api_key=api_key)


def _tidy(raw_text: str) -> str | None:
    """Turn a messy transcript into a clean note. Returns None if unavailable."""
    if not _anthropic_client:
        return None
    try:
        result = _anthropic_client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=(
                "You clean up voicemail transcripts for a spa's front desk. "
                "Rewrite the message into a short, clear note: who called, why, "
                "any callback number, and any requested action. Keep it factual "
                "and brief. Do not invent details."
            ),
            messages=[{"role": "user", "content": raw_text}],
        )
        return result.content[0].text
    except Exception:  # noqa: BLE001 - never let tidy-up break saving a note
        return None


app = FastAPI(title="vmedical-agent (local notes)", version="2.0.0")


@app.on_event("startup")
def _startup() -> None:
    notes_db.init_db()


def _save_note(
    note_type: str,
    raw_text: str,
    caller_name: str | None,
    caller_phone: str | None,
    source: str,
) -> dict:
    """
    Save a note everywhere it should go:
      1. Tidy it up with Claude (only if AI_CLEANUP=on).
      2. Write it into the Obsidian vault (the brain), if configured.
      3. Keep a local database copy as a reliable backup/log.
    """
    clean = _tidy(raw_text) if note_type == "voicemail" else None
    body = clean or raw_text

    vault_path = obsidian.write_note(
        note_type=note_type,
        body=body,
        caller_name=caller_name,
        caller_phone=caller_phone,
        source=source,
    )

    note_id = notes_db.add_note(
        note_type=note_type,
        raw_text=raw_text,
        caller_name=caller_name,
        caller_phone=caller_phone,
        clean_text=clean,
        source=source,
    )
    return {"id": note_id, "status": "saved", "obsidian_file": vault_path}


# --- Data shapes -------------------------------------------------------------
class NoteIn(BaseModel):
    note_type: str = "voicemail"       # "voicemail" or "appointment"
    raw_text: str
    caller_name: str | None = None
    caller_phone: str | None = None
    source: str = "manual"


# --- Health + simple viewer --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "ai_cleanup": AI_CLEANUP}


@app.get("/", response_class=HTMLResponse)
def viewer():
    """A plain, readable page of recent notes for the front desk."""
    notes = notes_db.list_notes()
    rows = []
    for n in notes:
        body = n["clean_text"] or n["raw_text"] or ""
        who = n["caller_name"] or "Unknown"
        phone = f" &middot; {n['caller_phone']}" if n["caller_phone"] else ""
        rows.append(
            f"<tr><td>{n['created_at']}</td>"
            f"<td><span class='tag'>{n['note_type']}</span></td>"
            f"<td><strong>{who}</strong>{phone}<br>{body}</td>"
            f"<td>{n['source']}</td></tr>"
        )
    table = "".join(rows) or (
        "<tr><td colspan='4' style='text-align:center;color:#888'>"
        "No notes yet.</td></tr>"
    )
    return f"""
    <html><head><title>Spa Notes</title>
    <meta http-equiv="refresh" content="30">
    <style>
      body {{ font-family: -apple-system, Arial, sans-serif; margin: 2rem;
              color: #222; }}
      h1 {{ font-size: 1.4rem; }}
      table {{ border-collapse: collapse; width: 100%; }}
      td, th {{ border-bottom: 1px solid #eee; padding: .6rem; text-align: left;
                vertical-align: top; }}
      th {{ color: #666; font-size: .8rem; text-transform: uppercase; }}
      .tag {{ background: #eef; border-radius: 4px; padding: .1rem .4rem;
              font-size: .8rem; }}
    </style></head>
    <body>
      <h1>Spa Notes <span style="font-weight:normal;color:#888;font-size:.9rem">
        (this page updates every 30 seconds)</span></h1>
      <table>
        <tr><th>When</th><th>Type</th><th>Note</th><th>Source</th></tr>
        {table}
      </table>
    </body></html>
    """


# --- Ways notes come in ------------------------------------------------------
@app.post("/api/notes")
def create_note(note: NoteIn):
    """Add a note directly (used for testing, or a manual entry form)."""
    return _save_note(
        note_type=note.note_type,
        raw_text=note.raw_text,
        caller_name=note.caller_name,
        caller_phone=note.caller_phone,
        source=note.source,
    )


@app.get("/api/notes")
def get_notes():
    """Return notes as data (for backups or other tools)."""
    return notes_db.list_notes()


@app.get("/api/history")
def client_history(q: str):
    """
    Look up a client's past notes from the Obsidian vault by name or phone.
    This is how an agent can pull context on a returning caller.
    """
    return {"query": q, "matches": obsidian.find_notes(q)}


@app.post("/webhook/ghl")
async def ghl_webhook(request: Request):
    """
    Receiving end for GoHighLevel.

    If you set up a GHL workflow with a 'Webhook' action pointing here, its
    data lands in this function. GHL field names vary by setup, so we look for
    the common ones and also keep the whole raw payload so nothing is lost.
    """
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Expected JSON body.") from exc

    # Best-effort mapping of common GHL fields. Adjust to match your workflow.
    name = (
        payload.get("full_name")
        or payload.get("contact_name")
        or f"{payload.get('first_name', '')} {payload.get('last_name', '')}".strip()
        or None
    )
    phone = payload.get("phone") or payload.get("caller_number")
    text = (
        payload.get("transcript")
        or payload.get("message")
        or payload.get("notes")
        or str(payload)
    )
    note_type = payload.get("note_type", "voicemail")

    return _save_note(
        note_type=note_type,
        raw_text=text,
        caller_name=name,
        caller_phone=phone,
        source="gohighlevel",
    )
