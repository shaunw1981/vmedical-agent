"""
obsidian.py — writes notes into the client's Obsidian vault (the "brain").

An Obsidian vault is just a folder of Markdown (.md) text files on this Mac.
This module drops each voicemail/appointment into that folder as a tidy note,
so it shows up in Obsidian automatically. It can also search existing notes so
an agent can look up a returning client's history.

Set OBSIDIAN_VAULT_PATH in .env to the folder Obsidian opens as the vault.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

# The vault folder. Notes are written into a subfolder so they stay tidy and
# never clobber anything the client already keeps in Obsidian.
VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
SUBFOLDER = os.environ.get("OBSIDIAN_SUBFOLDER", "vMedical Agent")


def _safe(text: str) -> str:
    """Make a string safe to use in a filename."""
    text = re.sub(r"[^\w\s-]", "", text or "").strip()
    return re.sub(r"\s+", " ", text) or "note"


def is_configured() -> bool:
    return bool(VAULT_PATH)


def write_note(
    note_type: str,
    body: str,
    caller_name: Optional[str] = None,
    caller_phone: Optional[str] = None,
    source: str = "manual",
) -> Optional[str]:
    """
    Write one note into the vault as a Markdown file.
    Returns the file path written, or None if the vault isn't configured.
    """
    if not VAULT_PATH:
        return None

    # Notes go into <vault>/<subfolder>/<Voicemails|Appointments>/
    kind_folder = "Appointments" if note_type == "appointment" else "Voicemails"
    folder = Path(VAULT_PATH) / SUBFOLDER / kind_folder
    folder.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d %H%M")
    who = _safe(caller_name or caller_phone or "Unknown")
    filename = f"{stamp} - {who}.md"
    path = folder / filename

    # Obsidian reads the "frontmatter" block (between ---) as searchable fields.
    contents = (
        "---\n"
        f"type: {note_type}\n"
        f"client: {caller_name or ''}\n"
        f"phone: {caller_phone or ''}\n"
        f"source: {source}\n"
        f"created: {now.isoformat(timespec='seconds')}\n"
        "---\n\n"
        f"# {note_type.title()} — {caller_name or 'Unknown'}\n\n"
        f"**When:** {now.strftime('%A %B %d, %Y at %I:%M %p')}  \n"
        f"**Phone:** {caller_phone or 'n/a'}  \n"
        f"**Source:** {source}\n\n"
        f"{body}\n"
    )
    path.write_text(contents, encoding="utf-8")
    return str(path)


def find_notes(query: str, limit: int = 10) -> list[dict]:
    """
    Search vault notes whose filename or contents contain `query`
    (e.g. a client's name or phone number). Lets an agent pull up history.
    """
    if not VAULT_PATH:
        return []
    base = Path(VAULT_PATH) / SUBFOLDER
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
