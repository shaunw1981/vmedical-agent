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
