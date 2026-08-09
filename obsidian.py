"""
obsidian.py — writes into the client's Obsidian vault (the "brain").

The vault is just a folder of Markdown files on this Mac. Everything is filed
*per client*, keyed by their phone number, so all of a caller's history builds
up in one place:

    <vault>/<subfolder>/Clients/<client>/Calls/<timestamp>.md
    <vault>/<subfolder>/Clients/<client>/Consults/...   (future: Granola notes)

Set OBSIDIAN_VAULT_PATH in .env to the folder Obsidian opens as the vault.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
SUBFOLDER = os.environ.get("OBSIDIAN_SUBFOLDER", "vMedical Agent")


def _safe(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text or "").strip()
    return re.sub(r"\s+", " ", text) or "unknown"


def is_configured() -> bool:
    return bool(VAULT_PATH)


def _client_folder(phone: str, name: Optional[str]) -> Path:
    """The per-client folder inside the vault, named for easy browsing."""
    label = _safe(f"{name} {phone}".strip()) if name else _safe(phone)
    return Path(VAULT_PATH) / SUBFOLDER / "Clients" / label


def write_call_transcript(
    phone: str,
    transcript: str,
    caller_name: Optional[str] = None,
    summary: Optional[str] = None,
    duration: Optional[str] = None,
    source: str = "gohighlevel",
) -> Optional[str]:
    """
    Write an after-hours call transcript into the caller's folder in the vault.
    Returns the file path, or None if the vault isn't configured.
    """
    if not VAULT_PATH:
        return None
    # Don't try to create the whole path from the filesystem root if the vault
    # folder itself is missing (e.g. the path is still the placeholder) — that
    # would fail with a confusing permission error.
    if not Path(VAULT_PATH).exists():
        raise FileNotFoundError(
            f"Obsidian vault folder not found: {VAULT_PATH} "
            "(check OBSIDIAN_VAULT_PATH in .env)"
        )

    folder = _client_folder(phone, caller_name) / "Calls"
    folder.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d %H%M")
    path = folder / f"{stamp} - after-hours call.md"

    summary_block = f"\n## Summary\n\n{summary}\n" if summary else ""
    duration_line = f"**Length:** {duration}  \n" if duration else ""
    contents = (
        "---\n"
        "type: call-transcript\n"
        f"client: {caller_name or ''}\n"
        f"phone: {phone}\n"
        f"duration: {duration or ''}\n"
        f"source: {source}\n"
        f"created: {now.isoformat(timespec='seconds')}\n"
        "---\n\n"
        f"# After-hours call — {caller_name or phone}\n\n"
        f"**When:** {now.strftime('%A %B %d, %Y at %I:%M %p')}  \n"
        f"**Phone:** {phone}  \n"
        f"{duration_line}"
        f"{summary_block}\n"
        "## Transcript\n\n"
        f"{transcript}\n"
    )
    path.write_text(contents, encoding="utf-8")
    return str(path)


def _stamp_slug(title: str) -> str:
    return _safe(title)[:60] or "meeting"


def write_consult_note(
    phone: Optional[str],
    name: Optional[str],
    title: str,
    summary: Optional[str] = None,
    transcript: Optional[str] = None,
    attendees: Optional[list[str]] = None,
    meeting_date: Optional[str] = None,
    source: str = "granola",
) -> Optional[str]:
    """
    File a confirmed Granola consult into the client's folder:

        <vault>/<subfolder>/Clients/<client>/Consults/<stamp> - <title>.md

    Charlie's retrieval scans the whole subfolder, so the transcript becomes
    referenceable the moment it's written. Returns the file path, or None if the
    vault isn't configured.
    """
    if not VAULT_PATH:
        return None
    if not Path(VAULT_PATH).exists():
        raise FileNotFoundError(
            f"Obsidian vault folder not found: {VAULT_PATH} "
            "(check OBSIDIAN_VAULT_PATH in .env)"
        )
    folder = _client_folder(phone or "", name) / "Consults"
    folder.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d %H%M")
    path = folder / f"{stamp} - {_stamp_slug(title)}.md"

    attendee_lines = "".join(f"  - {a}\n" for a in (attendees or []))
    summary_block = f"\n## Summary\n\n{summary}\n" if summary else ""
    transcript_block = f"\n## Transcript\n\n{transcript}\n" if transcript else ""
    contents = (
        "---\n"
        "type: client-consult\n"
        f"client: {name or ''}\n"
        f"phone: {phone or ''}\n"
        f"title: {title}\n"
        f"meeting_date: {meeting_date or ''}\n"
        f"source: {source}\n"
        f"created: {now.isoformat(timespec='seconds')}\n"
        + ("attendees:\n" + attendee_lines if attendee_lines else "")
        + "---\n\n"
        f"# Consult — {name or 'client'}: {title}\n\n"
        f"**When:** {meeting_date or now.strftime('%A %B %d, %Y')}  \n"
        f"{summary_block}"
        f"{transcript_block}"
    )
    path.write_text(contents, encoding="utf-8")
    return str(path)


def write_team_meeting(
    title: str,
    summary: Optional[str] = None,
    transcript: Optional[str] = None,
    attendees: Optional[list[str]] = None,
    meeting_date: Optional[str] = None,
    source: str = "granola",
) -> Optional[str]:
    """
    File a team/staff meeting into a shared folder:

        <vault>/<subfolder>/Team Meetings/<stamp> - <title>.md

    Returns the file path, or None if the vault isn't configured.
    """
    if not VAULT_PATH:
        return None
    if not Path(VAULT_PATH).exists():
        raise FileNotFoundError(
            f"Obsidian vault folder not found: {VAULT_PATH} "
            "(check OBSIDIAN_VAULT_PATH in .env)"
        )
    folder = Path(VAULT_PATH) / SUBFOLDER / "Team Meetings"
    folder.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d %H%M")
    path = folder / f"{stamp} - {_stamp_slug(title)}.md"

    attendee_lines = "".join(f"  - {a}\n" for a in (attendees or []))
    summary_block = f"\n## Summary\n\n{summary}\n" if summary else ""
    transcript_block = f"\n## Transcript\n\n{transcript}\n" if transcript else ""
    contents = (
        "---\n"
        "type: team-meeting\n"
        f"title: {title}\n"
        f"meeting_date: {meeting_date or ''}\n"
        f"source: {source}\n"
        f"created: {now.isoformat(timespec='seconds')}\n"
        + ("attendees:\n" + attendee_lines if attendee_lines else "")
        + "---\n\n"
        f"# Team meeting — {title}\n\n"
        f"**When:** {meeting_date or now.strftime('%A %B %d, %Y')}  \n"
        f"{summary_block}"
        f"{transcript_block}"
    )
    path.write_text(contents, encoding="utf-8")
    return str(path)


def find_client_notes(query: str, limit: int = 20) -> list[dict]:
    """Search the vault for notes matching a client's name or phone number."""
    if not VAULT_PATH:
        return []
    base = Path(VAULT_PATH) / SUBFOLDER / "Clients"
    if not base.exists():
        return []

    q = query.lower()
    hits: list[dict] = []
    for md in sorted(base.rglob("*.md"), reverse=True):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        if q in md.name.lower() or q in text.lower():
            hits.append({"path": str(md), "name": md.name, "text": text})
            if len(hits) >= limit:
                break
    return hits
