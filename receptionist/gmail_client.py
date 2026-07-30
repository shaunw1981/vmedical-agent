"""Gmail ingestion for the Receptionist agent.

Reads transcript emails from the dedicated mailbox (assistant@vmedical.ca) via
the Gmail API using a read-only OAuth credential.

Two files are involved (both gitignored):
  - credentials.json : the OAuth *client* downloaded from Google Cloud Console.
  - token.json       : the *user* token minted by authorize_gmail.py after a
                       one-time consent as the mailbox owner. Contains the
                       refresh token, so the agent never needs to log in again.

Least privilege: we request read-only scope. If we later want the agent to
label or mark messages as processed, bump the scope to gmail.modify and
re-run the authorize script.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .config import settings

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


@dataclass
class EmailMessage:
    id: str
    thread_id: str
    subject: str
    sender: str
    to: str
    date: str
    body_text: str
    snippet: str


def _load_credentials() -> Credentials:
    """Load stored OAuth credentials, refreshing the access token if needed."""
    creds = Credentials.from_authorized_user_file(settings.gmail_token_file, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(settings.gmail_token_file, "w") as f:
            f.write(creds.to_json())
    return creds


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _extract_plain_text(payload: dict) -> str:
    """Walk a MIME payload and return the best-effort plain-text body."""

    def decode(data: str) -> str:
        return base64.urlsafe_b64decode(data.encode("utf-8")).decode(
            "utf-8", errors="replace"
        )

    mime = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if mime == "text/plain" and body_data:
        return decode(body_data)

    # Prefer a text/plain part; fall back to stripped HTML if that's all there is.
    parts = payload.get("parts", []) or []
    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return decode(data)
    for part in parts:
        text = _extract_plain_text(part)
        if text:
            return text

    if mime == "text/html" and body_data:
        return decode(body_data)
    return ""


class GmailClient:
    def __init__(self):
        self._service = build("gmail", "v1", credentials=_load_credentials())

    def list_message_ids(self, query: str = "", max_results: int = 10) -> list[str]:
        """Return message IDs matching a Gmail search query (newest first)."""
        resp = (
            self._service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        return [m["id"] for m in resp.get("messages", [])]

    def get_message(self, message_id: str) -> EmailMessage:
        msg = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        return EmailMessage(
            id=msg["id"],
            thread_id=msg.get("threadId", ""),
            subject=_header(headers, "Subject"),
            sender=_header(headers, "From"),
            to=_header(headers, "To"),
            date=_header(headers, "Date"),
            body_text=_extract_plain_text(payload),
            snippet=msg.get("snippet", ""),
        )

    def latest_message(self, query: str = "") -> Optional[EmailMessage]:
        ids = self.list_message_ids(query=query, max_results=1)
        return self.get_message(ids[0]) if ids else None
