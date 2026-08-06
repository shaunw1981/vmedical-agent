"""
email_monitor.py — watches the assistant mailbox for "AI Call Recap" emails.

Every minute it logs into the mailbox (read-only-ish: it only marks messages as
read), finds new emails from the recap sender, pulls out the caller, number,
duration, summary, and transcript, and files each one into the dashboard and the
Obsidian vault — the same place the phone webhook would put it.

It runs quietly in the background inside the app. If the mailbox settings aren't
filled in (.env), it simply does nothing.
"""

import email
import html
import imaplib
import re
import threading
import time
from email.header import decode_header
from typing import Optional

import config
import db
import obsidian

# ---------------------------------------------------------------------------
# Parsing helpers — turn the email text into fields.
# ---------------------------------------------------------------------------
_PHONE_RE = re.compile(r"(\+?\d[\d\-().\s]{7,}\d)")


def _decode(value) -> str:
    """Decode an email header that may be MIME-encoded."""
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p\s*>", "\n", s)
    s = re.sub(r"(?i)</tr\s*>", "\n", s)
    s = re.sub(r"(?i)</td\s*>", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _get_body(msg) -> str:
    """Return the best plain-text body from an email message."""
    plain, htmltext = None, None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get("Content-Disposition", "").startswith("attachment"):
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                text = payload.decode(part.get_content_charset() or "utf-8", "replace")
            except Exception:  # noqa: BLE001
                continue
            if ctype == "text/plain" and plain is None:
                plain = text
            elif ctype == "text/html" and htmltext is None:
                htmltext = text
    else:
        payload = msg.get_payload(decode=True)
        text = payload.decode(msg.get_content_charset() or "utf-8", "replace") if payload else ""
        if msg.get_content_type() == "text/html":
            htmltext = text
        else:
            plain = text

    if plain and plain.strip():
        return plain.strip()
    if htmltext:
        return _strip_html(htmltext)
    return ""


def _label(text: str, labels) -> Optional[str]:
    for lab in labels:
        m = re.search(rf"(?im)^\s*{re.escape(lab)}\s*[:\-]\s*(.+?)\s*$", text)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def _section(text: str, start_labels, end_labels) -> Optional[str]:
    """Grab the block of text under a heading like 'Transcript:' up to the next."""
    for lab in start_labels:
        m = re.search(rf"(?im)^\s*{re.escape(lab)}\s*[:\-]?\s*$", text) or re.search(
            rf"(?im)^\s*{re.escape(lab)}\s*[:\-]\s*(.+)$", text
        )
        if not m:
            continue
        start = m.end()
        rest = text[start:]
        end = len(rest)
        for elab in end_labels:
            em = re.search(rf"(?im)^\s*{re.escape(elab)}\s*[:\-]?\s*$", rest)
            if em:
                end = min(end, em.start())
        block = rest[:end].strip()
        if block:
            return block
    return None


def _format_duration(d: Optional[str]) -> Optional[str]:
    """Turn '285 seconds' into a friendly '4m 45s'; leave other formats as-is."""
    if not d:
        return d
    m = re.match(r"^\s*(\d+)\s*seconds?\s*$", d, re.I)
    if not m:
        return d.strip()
    secs = int(m.group(1))
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m {secs % 60}s"


def _find_name(body: str) -> Optional[str]:
    """Find a caller name if the AI collected one (skips 'AI Agent Name')."""
    pattern = re.compile(
        r"(?im)^\s*(?:\d+\.\s*)?((?:full |caller |contact |first )?name)\s*[:\-]\s*(.+?)\s*$"
    )
    for m in pattern.finditer(body):
        label, value = m.group(1).lower(), m.group(2).strip()
        if "agent" in label:
            continue
        if value and value.lower() not in ("n/a", "none", "unknown", "not provided"):
            return value
    return None


def parse_recap(subject: str, body: str) -> dict:
    """
    Extract fields from a Client Connector / GHL "AI Call Recap" email. Whatever
    we can't confidently split out still ends up in the transcript, so nothing is
    ever lost.
    """
    phone_raw = _label(body, ["Caller's Number", "Callers Number", "Caller Number",
                              "From", "CallFrom", "Phone Number", "Phone"])
    phone = None
    if phone_raw:
        pm = _PHONE_RE.search(phone_raw)
        phone = pm.group(1).strip() if pm else phone_raw.strip()
    if not phone:
        pm = _PHONE_RE.search(body)
        phone = pm.group(1).strip() if pm else "unknown"

    name = _find_name(body)
    duration = _format_duration(
        _label(body, ["Call Duration", "Duration", "Call Length", "Length"])
    )
    summary = _section(
        body, ["Call Summary", "Summary"],
        ["Details collected from the contact", "Details collected",
         "Call Transcript", "Transcript"],
    )
    transcript = _section(body, ["Call Transcript", "Transcript"], [])
    if not transcript:
        transcript = body  # fall back to the whole email so nothing is lost

    return {
        "phone": phone,
        "name": name,
        "duration": duration,
        "summary": summary,
        "transcript": transcript,
    }


# ---------------------------------------------------------------------------
# Mailbox polling.
# ---------------------------------------------------------------------------
def poll_once() -> int:
    """Check the inbox for new recap emails and save any found. Returns count."""
    if not config.email_monitor_enabled():
        return 0

    saved = 0
    imap = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT)
    try:
        imap.login(config.IMAP_USER, config.IMAP_PASSWORD)
        imap.select("INBOX")
        # Unread messages from the recap sender.
        typ, data = imap.search(None, "UNSEEN", "FROM", config.RECAP_FROM)
        ids = data[0].split() if data and data[0] else []
        for num in ids:
            # BODY.PEEK reads the email WITHOUT marking it read — we only mark
            # it read ourselves after it's been saved, so a transient error
            # never silently consumes an email.
            typ, msg_data = imap.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode(msg.get("Subject"))
            if config.RECAP_SUBJECT_PREFIX.lower() not in subject.lower():
                continue  # not a recap; leave it untouched (don't mark read)

            message_id = _decode(msg.get("Message-ID")) or f"{subject}-{num.decode()}"
            body = _get_body(msg)
            fields = parse_recap(subject, body)

            client = db.get_or_create_client(fields["phone"], fields["name"])
            # Writing to Obsidian is secondary — never let a vault problem stop
            # the call from reaching the dashboard.
            vault_file = None
            try:
                vault_file = obsidian.write_call_transcript(
                    phone=fields["phone"], transcript=fields["transcript"],
                    caller_name=fields["name"], summary=fields["summary"],
                    duration=fields["duration"],
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[email_monitor] Obsidian write skipped: {exc}")
            try:
                db.add_message(
                    client_id=client["id"],
                    transcript=fields["transcript"],
                    summary=fields["summary"],
                    duration=fields["duration"],
                    obsidian_file=vault_file,
                    ghl_call_id=message_id,
                )
                saved += 1
            except Exception:  # noqa: BLE001 - already saved (duplicate Message-ID)
                pass
            # Mark as read so we don't process it again (even if Obsidian failed).
            imap.store(num, "+FLAGS", "\\Seen")
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    if saved:
        print(f"[email_monitor] saved {saved} new call recap(s)")
    return saved


def _loop() -> None:
    while True:
        try:
            poll_once()
        except Exception as exc:  # noqa: BLE001 - never let the loop die
            print(f"[email_monitor] error: {exc}")
        time.sleep(config.EMAIL_POLL_SECONDS)


def start_background() -> None:
    """Start the mailbox watcher in a background thread, if it's configured."""
    if not config.email_monitor_enabled():
        print("[email_monitor] not configured (IMAP settings blank) — skipping.")
        return
    t = threading.Thread(target=_loop, name="email-monitor", daemon=True)
    t.start()
    print(f"[email_monitor] watching {config.IMAP_USER} every "
          f"{config.EMAIL_POLL_SECONDS}s")
