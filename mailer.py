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

import config


def enabled() -> bool:
    return config.email_send_enabled()


def send_email(to: str, subject: str, body: str) -> dict:
    """Send a plain-text email. Raises on failure."""
    to = (to or "").strip()
    if not enabled():
        raise RuntimeError("Email sending isn't set up (IMAP_USER / IMAP_PASSWORD).")
    if not to:
        raise ValueError("No recipient email address.")

    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM or config.IMAP_USER
    msg["To"] = to
    msg["Subject"] = (subject or "").strip() or "A message from Valley Medical"
    msg.set_content(body or "")

    ctx = ssl.create_default_context()
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as server:
        server.starttls(context=ctx)
        server.login(config.IMAP_USER, config.IMAP_PASSWORD)
        server.send_message(msg)
    return {"ok": True, "to": to}
