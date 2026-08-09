"""
granola.py — pulls meeting notes from Granola's public API.

Granola records meetings (client consults + team meetings) and produces an AI
summary and a transcript for each. This module reads them through Granola's
public REST API and sorts each meeting into one of two buckets by the Granola
folder it lives in:

    "Client Consults"  → the intake queue (a team member confirms the client)
    "Team Meeting"      → the Team/Staff meetings section

Auth is a workspace API key (starts with ``grn_``) created in the Granola
desktop app. Put it in .env as GRANOLA_API_KEY. See config.py / .env.example.

The exact public-API response shapes can't be verified from the build box, so
every field is read defensively (several possible key names) and the raw
responses are exposed at /meetings?debug=1 so we can confirm/adjust on the Mac.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

import config


# --- Config helpers ----------------------------------------------------------

def is_configured() -> bool:
    return bool(config.GRANOLA_API_KEY)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.GRANOLA_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


# --- Low-level HTTP ----------------------------------------------------------

def _get(path: str, params: Optional[dict] = None) -> dict:
    url = f"{config.GRANOLA_API_BASE}{path}"
    with httpx.Client(timeout=30) as client:
        r = client.get(url, headers=_headers(), params=params)
    return _handle(r)


def _post(path: str, body: dict) -> dict:
    url = f"{config.GRANOLA_API_BASE}{path}"
    with httpx.Client(timeout=30) as client:
        r = client.post(url, headers=_headers(), json=body)
    return _handle(r)


def _handle(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        snippet = (r.text or "").strip()
        if len(snippet) > 300:
            snippet = snippet[:300] + "…"
        raise RuntimeError(
            f"Granola API returned {r.status_code} for {r.request.url.path}. {snippet}"
        )
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {"_list": data}


# --- Field helpers -----------------------------------------------------------

def _first(d: Any, *keys: str, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _text_from(value: Any) -> str:
    """
    Flatten a note/summary field to plain text. Handles a plain string, a list
    of blocks, or a ProseMirror-style document ({type, content:[...], text}).
    """
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value.strip()
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, dict):
            if isinstance(node.get("text"), str):
                parts.append(node["text"])
            for key in ("content", "children", "blocks"):
                if isinstance(node.get(key), list):
                    for child in node[key]:
                        walk(child)
            # ProseMirror block boundaries → newlines for readability.
            if node.get("type") in ("paragraph", "heading", "listItem", "bulletList"):
                parts.append("\n")
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    text = "".join(parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _note_summary(note: dict) -> str:
    for key in ("summary", "ai_summary", "notes_markdown", "notes", "overview",
                "content", "last_viewed_panel"):
        val = note.get(key)
        if isinstance(val, dict):
            val = val.get("content", val)
        text = _text_from(val)
        if text:
            return text
    return ""


def _note_attendees(note: dict) -> list[str]:
    raw = _first(note, "attendees", "people", "participants",
                 "known_participants", default=[])
    out: list[str] = []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    for p in raw or []:
        if isinstance(p, str):
            name = p.strip()
        elif isinstance(p, dict):
            name = (_first(p, "name", "display_name", "full_name", default="") or "").strip()
            email = (_first(p, "email", default="") or "").strip()
            if name and email:
                name = f"{name} <{email}>"
            elif email and not name:
                name = email
        else:
            name = ""
        if name:
            out.append(name)
    return out


def _note_folders(note: dict) -> list[str]:
    """Every folder/list name this note belongs to (defensive across shapes)."""
    names: list[str] = []
    raw = _first(note, "folders", "lists", "document_lists", "collections", default=None)
    if isinstance(raw, list):
        for f in raw:
            if isinstance(f, dict):
                nm = _first(f, "name", "title", "label", default="")
            else:
                nm = str(f)
            if nm:
                names.append(str(nm).strip())
    # Single-folder shapes.
    for key in ("folder", "folder_name", "list", "list_name"):
        val = note.get(key)
        if isinstance(val, dict):
            val = _first(val, "name", "title", default="")
        if isinstance(val, str) and val.strip():
            names.append(val.strip())
    return names


def _note_created(note: dict) -> str:
    raw = _first(note, "created_at", "created", "createdAt", "date",
                 "start_time", "started_at", default="")
    return _iso(_parse_dt(raw)) if raw else ""


def _parse_dt(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            # Heuristic: ms vs s epoch.
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value,
                                          tz=timezone.utc)
        except (ValueError, OSError):
            return None
    if isinstance(value, str):
        s = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _iso(dt: Optional[datetime]) -> str:
    return dt.astimezone(timezone.utc).isoformat() if dt else ""


# --- Categorization ----------------------------------------------------------

def _matches(name: str, wanted: list[str]) -> bool:
    n = (name or "").strip().lower()
    return any(n == w or w in n or n in w for w in wanted if w)


def categorize(folder_names: list[str]) -> Optional[str]:
    """'client', 'team', or None based on the configured folder-name lists."""
    client = [w.lower() for w in config.GRANOLA_CLIENT_FOLDERS]
    team = [w.lower() for w in config.GRANOLA_TEAM_FOLDERS]
    for nm in folder_names:
        if _matches(nm, client):
            return "client"
    for nm in folder_names:
        if _matches(nm, team):
            return "team"
    return None


# --- Public API calls --------------------------------------------------------

def list_folders() -> list[dict]:
    """All Granola folders (id + name), best-effort."""
    try:
        data = _get("/folders")
    except Exception:  # noqa: BLE001
        return []
    rows = data.get("folders") or data.get("lists") or data.get("data") \
        or data.get("_list") or []
    out = []
    for f in rows or []:
        if not isinstance(f, dict):
            continue
        out.append({
            "id": str(_first(f, "id", "_id", "document_list_id", default="")),
            "name": _first(f, "name", "title", "label", default=""),
        })
    return out


def list_notes(created_after: Optional[datetime] = None,
               page_size: int = 100, max_pages: int = 20) -> list[dict]:
    """Raw note objects from GET /notes, following cursor pagination."""
    notes: list[dict] = []
    cursor: Optional[str] = None
    for _ in range(max_pages):
        params: dict = {"page_size": page_size, "limit": page_size}
        if created_after:
            params["created_after"] = _iso(created_after)
        if cursor:
            params["cursor"] = cursor
        data = _get("/notes", params=params)
        page = data.get("notes") or data.get("documents") or data.get("data") \
            or data.get("_list") or []
        notes.extend([n for n in page if isinstance(n, dict)])
        cursor = _first(data, "cursor", "next_cursor", "nextCursor")
        has_more = _first(data, "has_more", "hasMore", default=bool(cursor and page))
        if not has_more or not cursor or not page:
            break
    return notes


def get_transcript(note_id: str) -> str:
    """Full transcript text for a note, with speaker labels, best-effort."""
    data: dict = {}
    for path in (f"/notes/{note_id}/transcript", f"/transcripts/{note_id}"):
        try:
            data = _get(path)
            break
        except Exception:  # noqa: BLE001
            continue
    if not data:
        return ""
    raw = data.get("transcript")
    if raw is None:
        raw = data.get("segments") or data.get("utterances") or data.get("_list") or data
    # Plain string transcript.
    if isinstance(raw, str):
        return raw.strip()
    # List of utterance objects.
    if isinstance(raw, list):
        lines: list[str] = []
        for u in raw:
            if not isinstance(u, dict):
                lines.append(str(u))
                continue
            who = _first(u, "speaker", "speaker_name", "source", default="")
            if (who or "").lower() == "microphone":
                who = "Me"
            elif (who or "").lower() == "system":
                who = "Them"
            text = _first(u, "text", "content", default="")
            lines.append(f"{who}: {text}".strip(": ").strip() if who else str(text))
        return "\n".join(l for l in lines if l).strip()
    return ""


# --- Normalized fetch (for the intake queue) ---------------------------------

def fetch_recent(days: int = 30, with_transcripts: bool = True) -> list[dict]:
    """
    Recent client-consult + team meetings, normalized for storage. Only notes
    that fall into one of the two configured folders are returned.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    notes = list_notes(created_after=since)

    # If notes don't carry folder membership, fall back to folder→document_ids.
    folder_index: dict[str, list[str]] = {}
    if notes and not _note_folders(notes[0]):
        folder_index = _build_folder_index()

    out: list[dict] = []
    for n in notes:
        nid = str(_first(n, "id", "_id", "document_id", default=""))
        if not nid:
            continue
        folders = _note_folders(n) or folder_index.get(nid, [])
        category = categorize(folders)
        if category is None:
            continue
        rec = {
            "granola_id": nid,
            "category": category,
            "title": _first(n, "title", "name", default="(untitled meeting)"),
            "meeting_date": _note_created(n),
            "folder": folders[0] if folders else "",
            "attendees": _note_attendees(n),
            "summary": _note_summary(n),
            "transcript": "",
        }
        if with_transcripts:
            try:
                rec["transcript"] = get_transcript(nid)
            except Exception:  # noqa: BLE001
                rec["transcript"] = ""
        out.append(rec)
    return out


def _build_folder_index() -> dict[str, list[str]]:
    """Map document-id → [folder names], for APIs that keep folders separate."""
    index: dict[str, list[str]] = {}
    try:
        data = _get("/folders")
    except Exception:  # noqa: BLE001
        return index
    rows = data.get("folders") or data.get("lists") or data.get("_list") or []
    for f in rows or []:
        if not isinstance(f, dict):
            continue
        name = _first(f, "name", "title", "label", default="")
        doc_ids = _first(f, "document_ids", "note_ids", "documentIds", default=None)
        if doc_ids is None:
            docs = _first(f, "documents", "notes", default=[]) or []
            doc_ids = [str(_first(d, "id", "_id", default="")) for d in docs
                       if isinstance(d, dict)]
        for did in doc_ids or []:
            index.setdefault(str(did), []).append(name)
    return index


# --- Diagnostics -------------------------------------------------------------

_REDACT_RE = re.compile(r"token|secret|password|api[_-]?key|authorization", re.I)


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if _REDACT_RE.search(k) else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj[:5]]  # cap list length in the dump
    return obj


def debug() -> dict:
    """Credential-redacted connectivity + parsed sample, for /meetings?debug=1."""
    out: dict = {
        "configured": is_configured(),
        "api_base": config.GRANOLA_API_BASE,
        "client_folders": config.GRANOLA_CLIENT_FOLDERS,
        "team_folders": config.GRANOLA_TEAM_FOLDERS,
    }
    if not is_configured():
        return out
    try:
        out["folders"] = list_folders()
    except Exception as exc:  # noqa: BLE001
        out["folders_error"] = str(exc)
    try:
        raw = _get("/notes", params={"page_size": 3, "limit": 3})
        out["notes_raw_sample"] = _redact(raw)
    except Exception as exc:  # noqa: BLE001
        out["notes_error"] = str(exc)
    try:
        parsed = fetch_recent(days=60, with_transcripts=False)
        out["parsed_count"] = len(parsed)
        out["parsed_sample"] = [
            {k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v)
             for k, v in m.items() if k != "transcript"}
            for m in parsed[:3]
        ]
    except Exception as exc:  # noqa: BLE001
        out["parsed_error"] = str(exc)
    return out
