"""
mailer.py — sends email from the clinic's assistant mailbox (SMTP).

Reuses the same Google account + app password as the email monitor (IMAP_USER /
IMAP_PASSWORD), so there's no separate credential to set up. Only ever called
after a human approves a message Charlie drafted.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

import config


def enabled() -> bool:
    return config.email_send_enabled()


def send_email(to: str, subject: str, body: str,
               from_addr: Optional[str] = None, reply_to: Optional[str] = None) -> dict:
    """Send a plain-text email. Raises on failure.

    from_addr sets the visible From (defaults to SMTP_FROM / IMAP_USER). Note the
    authenticated mailbox must be allowed to send as that address, or the mail
    server may rewrite or reject it.
    """
    to = (to or "").strip()
    if not enabled():
        raise RuntimeError("Email sending isn't set up (IMAP_USER / IMAP_PASSWORD).")
    if not to:
        raise ValueError("No recipient email address.")

    msg = EmailMessage()
    msg["From"] = (from_addr or "").strip() or config.SMTP_FROM or config.IMAP_USER
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to.strip()
    msg["Subject"] = (subject or "").strip() or "A message from Valley Medical"
    msg.set_content(body or "")

    ctx = ssl.create_default_context()
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as server:
        server.starttls(context=ctx)
        server.login(config.IMAP_USER, config.IMAP_PASSWORD)
        server.send_message(msg)
    return {"ok": True, "to": to}
