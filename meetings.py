"""
meetings.py — turns Granola meeting notes into client + team records.

Two jobs:
  * sync()    — pull recent meetings from Granola into the local queue. Team
                meetings are filed to Obsidian automatically; client consults
                wait in the queue for a team member to confirm the client.
  * confirm() — attach a queued consult to a client: file a consult note (with
                transcript) into that client's Obsidian folder so Charlie can
                reference it, add a note to the GHL contact, and mark it done.
"""

from __future__ import annotations

from typing import Optional

import config
import db
import ghl
import granola
import obsidian


def _attendees_text(attendees) -> str:
    if isinstance(attendees, list):
        return "\n".join(a for a in attendees if a)
    return attendees or ""


def _attendees_list(text: Optional[str]) -> list[str]:
    return [line for line in (text or "").splitlines() if line.strip()]


# --- Sync from Granola -------------------------------------------------------

def sync(days: Optional[int] = None) -> dict:
    """
    Pull recent meetings from Granola into the queue. Returns a summary dict:
    {"ok", "new_client", "new_team", "total", "error"?, "warnings":[...]}.
    """
    if not config.granola_enabled():
        return {"ok": False, "error": "Granola isn't connected yet (set GRANOLA_API_KEY)."}
    days = days or config.GRANOLA_SYNC_DAYS
    try:
        meetings = granola.fetch_recent(days=days, with_transcripts=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Couldn't reach Granola: {exc}"}

    new_client = new_team = 0
    warnings: list[str] = []
    for m in meetings:
        rec = db.upsert_meeting(
            granola_id=m["granola_id"],
            category=m["category"],
            title=m.get("title") or "(untitled meeting)",
            meeting_date=m.get("meeting_date"),
            folder=m.get("folder"),
            attendees=_attendees_text(m.get("attendees")),
            summary=m.get("summary"),
            transcript=m.get("transcript"),
        )
        if not rec["new"]:
            continue
        if m["category"] == "team":
            new_team += 1
            # File team meetings to Obsidian straight away.
            if obsidian.is_configured():
                try:
                    path = obsidian.write_team_meeting(
                        title=m.get("title") or "(untitled meeting)",
                        summary=m.get("summary"),
                        transcript=m.get("transcript"),
                        attendees=m.get("attendees") or [],
                        meeting_date=m.get("meeting_date"),
                    )
                    if path:
                        db.set_meeting_obsidian_file(rec["id"], path)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Team meeting “{m.get('title')}” not filed to Obsidian: {exc}")
        else:
            new_client += 1

    return {
        "ok": True,
        "new_client": new_client,
        "new_team": new_team,
        "total": len(meetings),
        "warnings": warnings,
    }


# --- Confirm a consult → a client -------------------------------------------

def confirm(meeting_id: int, actor: str, contact_id: str = "",
            name: str = "", phone: str = "", email: str = "") -> dict:
    """
    Attach a queued client consult to a client. Resolves the GHL contact (by id,
    or upserts from the entered details), files the consult note + transcript to
    the client's Obsidian folder, adds a note to the GHL contact, and marks the
    queue item confirmed. Returns {"ok", "client_name", "warnings":[...], "error"?}.
    """
    m = db.get_meeting(meeting_id)
    if not m:
        return {"ok": False, "error": "That meeting is no longer in the queue."}
    if m["category"] != "client":
        return {"ok": False, "error": "Only client consults can be assigned to a client."}
    if m["status"] == "confirmed":
        return {"ok": False, "error": "This consult was already confirmed."}

    contact_id = (contact_id or "").strip()
    name = (name or "").strip()
    phone = (phone or "").strip()
    email = (email or "").strip()
    warnings: list[str] = []

    # Resolve the GHL contact.
    if config.ghl_contacts_enabled():
        loc = config.reminder_location_id()
        if contact_id:
            # Fill in any missing details from the contact record.
            try:
                c = ghl.get_contact(contact_id)
                name = name or c.get("name") or ""
                phone = phone or c.get("phone") or ""
                email = email or c.get("email") or ""
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Couldn't load contact details: {exc}")
        else:
            if not name and not phone and not email:
                return {"ok": False, "error": "Pick a contact or enter a name."}
            try:
                created = ghl.upsert_contact(loc, name=name or (email or phone),
                                             email=email or None, phone=phone or None)
                contact_id = created["id"]
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"Couldn't create/find the contact in GoHighLevel: {exc}"}
    elif not name:
        return {"ok": False, "error": "Enter the client's name."}

    display_name = name or email or phone or "client"

    # File the consult note + transcript into the client's Obsidian folder.
    obsidian_file = None
    if obsidian.is_configured():
        try:
            obsidian_file = obsidian.write_consult_note(
                phone=phone, name=display_name,
                title=m.get("title") or "Consult",
                summary=m.get("summary"),
                transcript=m.get("transcript"),
                attendees=_attendees_list(m.get("attendees")),
                meeting_date=m.get("meeting_date"),
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Consult not filed to Obsidian: {exc}")

    # Add a note to the GHL contact.
    ghl_note_id = None
    if contact_id and config.ghl_contacts_enabled():
        try:
            resp = ghl.add_contact_note(contact_id, _ghl_note_body(m))
            note = resp.get("note") if isinstance(resp, dict) else None
            ghl_note_id = str((note or resp or {}).get("id", "")) or None
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Note not added to GoHighLevel: {exc}")

    db.confirm_meeting(
        meeting_id, contact_id=contact_id, client_name=display_name,
        confirmed_by=actor, client_phone=phone or None, client_email=email or None,
        obsidian_file=obsidian_file, ghl_note_id=ghl_note_id,
    )
    return {"ok": True, "client_name": display_name, "contact_id": contact_id,
            "warnings": warnings}


def _ghl_note_body(m: dict) -> str:
    """A compact contact-note body — the full transcript lives in Obsidian."""
    when = m.get("meeting_date") or ""
    lines = [f"Consult — {m.get('title') or 'meeting'}"]
    if when:
        lines.append(f"When: {when}")
    summary = (m.get("summary") or "").strip()
    if summary:
        if len(summary) > 1500:
            summary = summary[:1500].rstrip() + "…"
        lines.append("")
        lines.append(summary)
    lines.append("")
    lines.append("Full transcript filed in the clinic knowledge base "
                 "(Charlie can reference it).")
    return "\n".join(lines)
