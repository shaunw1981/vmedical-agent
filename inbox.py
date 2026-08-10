"""
inbox.py — Charlie's conversation inbox.

When a contact texts back (after Charlie reached out), the reply lands here.
Charlie reads the thread + the clinic knowledge base and either:
  * prepares a suggested draft reply for a team member to send, or
  * hands off — she can't answer confidently/safely — and emails
    hello@vmedical.ca (INBOX_ESCALATION_EMAIL) for clarity.

A team member, from the Inbox, can send Charlie's draft (editing first if they
like), give Charlie direction and let her redraft, or take the conversation over
themselves (which closes it). Nothing is ever sent to the contact automatically
— every outbound message needs a team member's click.
"""

from __future__ import annotations

from typing import Optional

import config
import charlie
import db
import ghl
import mailer


def _history(convo_id: int) -> list[dict]:
    return [{"role": m["role"], "body": m["body"]}
            for m in db.list_convo_messages(convo_id)]


def _last_contact_text(convo_id: int) -> str:
    for m in reversed(db.list_convo_messages(convo_id)):
        if m["role"] == "contact":
            return m["body"]
    return ""


def _escalate_email(convo: dict, question: str) -> Optional[str]:
    """Email the team for clarity. Returns a warning string on failure, else None."""
    if not config.email_send_enabled():
        return "email isn't set up, so the team wasn't emailed — check the Inbox"
    who = convo.get("contact_name") or convo.get("phone") or "a contact"
    recent = db.list_convo_messages(convo["id"])[-6:]
    thread = "\n".join(f"- {m['role']}: {m['body']}" for m in recent)
    body = (
        f"{config.CHARLIE_NAME} needs a hand replying to {who}"
        f"{(' (' + convo['phone'] + ')') if convo.get('phone') else ''}.\n\n"
        f"What I need clarity on:\n{question}\n\n"
        f"Recent messages:\n{thread}\n\n"
        f"Direct me or take it over here: {config.BASE_URL}/inbox\n"
    )
    try:
        mailer.send_email(config.INBOX_ESCALATION_EMAIL,
                          f"[{config.CHARLIE_NAME}] Needs help replying to {who}", body)
        return None
    except Exception as exc:  # noqa: BLE001
        return f"couldn't email {config.INBOX_ESCALATION_EMAIL}: {exc}"


def _apply_result(convo: dict, result: dict) -> dict:
    """Turn a charlie.converse() result into inbox state (draft or hand-off)."""
    warnings: list[str] = []
    if result.get("ok") and result.get("action") == "reply":
        db.set_convo_attention(convo["id"], "draft", draft=result["message"])
        return {"ok": True, "outcome": "draft", "warnings": warnings}
    # Hand off (either an explicit escalation or any failure).
    question = result.get("question") or result.get("error") \
        or f"{config.CHARLIE_NAME} wasn't sure how to answer this."
    db.set_convo_attention(convo["id"], "handoff", handoff_note=question)
    warn = _escalate_email(convo, question)
    if warn:
        warnings.append(warn)
    return {"ok": True, "outcome": "handoff", "warnings": warnings}


def handle_inbound(phone: Optional[str], text: str, contact_id: Optional[str] = None,
                   name: Optional[str] = None, email: Optional[str] = None) -> dict:
    """Record an inbound text and let Charlie draft a reply or hand off."""
    text = (text or "").strip()
    convo = db.get_or_create_convo(phone=phone, contact_id=contact_id,
                                   contact_name=name, email=email)
    if text:
        db.add_inbox_message(convo["id"], "contact", text, via="sms")

    history = _history(convo["id"])
    result = charlie.converse(convo.get("contact_name"), history, text)
    out = _apply_result(db.get_convo(convo["id"]), result)
    out["convo_id"] = convo["id"]
    return out


def direct(convo_id: int, direction: str, actor: str) -> dict:
    """A team member tells Charlie how to reply; Charlie redrafts from that."""
    convo = db.get_convo(convo_id)
    if not convo or convo["status"] != "open":
        return {"ok": False, "error": "That conversation isn't open."}
    direction = (direction or "").strip()
    if not direction:
        return {"ok": False, "error": "Add some direction for Charlie first."}
    db.add_inbox_message(convo_id, "team", f"Direction to {config.CHARLIE_NAME}: {direction}",
                         via="note")
    result = charlie.converse(convo.get("contact_name"), _history(convo_id),
                              _last_contact_text(convo_id), direction=direction)
    return _apply_result(db.get_convo(convo_id), result)


def send_reply(convo_id: int, body: str, actor: str) -> dict:
    """Send a reply to the contact (Charlie's draft, possibly edited by the team)."""
    convo = db.get_convo(convo_id)
    if not convo or convo["status"] != "open":
        return {"ok": False, "error": "That conversation isn't open."}
    body = (body or "").strip()
    if not body:
        return {"ok": False, "error": "The reply is empty."}
    if not config.ghl_contacts_enabled():
        return {"ok": False, "error": "GoHighLevel isn't connected, so the text can't be sent."}
    contact_id = convo.get("contact_id")
    try:
        if not contact_id:
            c = ghl.upsert_contact(config.reminder_location_id(),
                                   name=convo.get("contact_name") or convo.get("phone") or "Contact",
                                   phone=convo.get("phone") or None,
                                   email=convo.get("email") or None)
            contact_id = c["id"]
            db.set_convo_contact_id(convo_id, contact_id)
        ghl.send_sms(contact_id, body)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Couldn't send the text: {exc}"}
    db.add_inbox_message(convo_id, "charlie", body, via="sms")
    db.set_convo_attention(convo_id, "none")
    return {"ok": True}


def take_over(convo_id: int, actor: str) -> dict:
    """A team member will handle this contact directly; close the conversation."""
    convo = db.get_convo(convo_id)
    if not convo:
        return {"ok": False, "error": "Conversation not found."}
    db.add_inbox_message(convo_id, "system", f"{actor} took this over — Charlie will step back.",
                         via="note")
    db.close_convo(convo_id, by=actor, reason="team handling")
    return {"ok": True}


def start_from_outreach(phone: Optional[str], body: str, contact_id: Optional[str] = None,
                        name: Optional[str] = None, email: Optional[str] = None) -> Optional[int]:
    """
    Record an outbound text Charlie sent (approved by a team member) so the
    contact's reply threads back into the same conversation. Returns convo id.
    """
    convo = db.get_or_create_convo(phone=phone, contact_id=contact_id,
                                   contact_name=name, email=email)
    if body:
        db.add_inbox_message(convo["id"], "charlie", body, via="sms")
    return convo["id"]
