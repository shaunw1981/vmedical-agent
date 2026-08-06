"""
ghl_sync.py — STARTER for pulling notes from GoHighLevel into the local app.

Why "pull" instead of "push":
  The Mac Mini sits behind the spa's internet router, so the outside world
  (including GoHighLevel) can't easily reach IN to it. But the Mac CAN reach
  OUT to the internet. So the simplest, safest setup is: this script runs on a
  schedule, asks GoHighLevel "anything new?", and saves what it finds locally.

Status: this is a STARTER. The core app already works and stores notes. To turn
this on you need to (a) create a GoHighLevel API token, (b) confirm the exact
endpoints for your account, and (c) schedule this to run (SETUP-MACMINI.md
explains all of that). Until GHL_API_TOKEN is set in .env, it does nothing.

You can run it any time to test:  python ghl_sync.py
"""

import os

import httpx
from dotenv import load_dotenv

import notes_db
import obsidian

load_dotenv()

GHL_API_TOKEN = os.environ.get("GHL_API_TOKEN", "").strip()
GHL_LOCATION_ID = os.environ.get("GHL_LOCATION_ID", "").strip()

# GoHighLevel's API base. The "Version" header is required by their v2 API.
API_BASE = "https://services.leadconnectorhq.com"
HEADERS = {
    "Authorization": f"Bearer {GHL_API_TOKEN}",
    "Version": "2021-07-28",
    "Accept": "application/json",
}


def fetch_recent_conversations() -> list[dict]:
    """
    Ask GoHighLevel for recent conversations (which include voicemails/calls).

    NOTE: GHL has several endpoints and your exact plan may differ. Confirm the
    right one for your account in GHL's API docs, then adjust the path/params
    below. This is intentionally conservative and read-only.
    """
    url = f"{API_BASE}/conversations/search"
    params = {"locationId": GHL_LOCATION_ID, "limit": 20}
    resp = httpx.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("conversations", [])


def sync_once() -> int:
    """Pull recent items and save any that look like new notes. Returns count."""
    if not GHL_API_TOKEN or not GHL_LOCATION_ID:
        print(
            "GHL_API_TOKEN / GHL_LOCATION_ID are not set in .env — nothing to do.\n"
            "See SETUP-MACMINI.md, 'Connecting GoHighLevel', when you're ready."
        )
        return 0

    saved = 0
    for convo in fetch_recent_conversations():
        text = convo.get("lastMessageBody") or convo.get("body")
        if not text:
            continue
        name = convo.get("fullName") or convo.get("contactName")
        phone = convo.get("phone")
        # Write into the Obsidian vault (the brain)...
        obsidian.write_note(
            note_type="voicemail",
            body=text,
            caller_name=name,
            caller_phone=phone,
            source="gohighlevel",
        )
        # ...and keep a local database copy as backup.
        notes_db.add_note(
            note_type="voicemail",
            raw_text=text,
            caller_name=name,
            caller_phone=phone,
            source="gohighlevel",
        )
        saved += 1

    print(f"Saved {saved} note(s) from GoHighLevel.")
    return saved


if __name__ == "__main__":
    notes_db.init_db()
    sync_once()
