"""
ghl.py — reads social-media analytics from GoHighLevel's Social Planner.

Two endpoints do the work (schemas confirmed against GHL's public OpenAPI):
  • GET  /social-media-posting/{locationId}/accounts    — connected pages
  • POST /social-media-posting/statistics?locationId=…  — Advanced Analytics:
        body {"profileIds": [...], "platforms": [...]}; returns totals
        (posts, likes, followers, impressions, comments) and breakdowns for
        reach / impressions / engagement / posts, each with the change vs the
        previous 7 days. profileIds come from each account's "profileId".
  • POST /social-media-posting/{locationId}/posts/list  — recent/scheduled posts
        (used for "last posted" and "scheduled" context).

Auth: a sub-account Private Integration Token with the read-only Social Planner
scopes. See config.py / .env.example.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

import config


# --- Low-level HTTP ----------------------------------------------------------

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.GHL_API_TOKEN}",
        "Version": config.GHL_API_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _get(path: str, params: Optional[dict] = None) -> dict:
    url = f"{config.GHL_API_BASE}{path}"
    with httpx.Client(timeout=20) as client:
        r = client.get(url, headers=_headers(), params=params)
    return _handle(r)


def _post(path: str, body: dict, params: Optional[dict] = None) -> dict:
    url = f"{config.GHL_API_BASE}{path}"
    with httpx.Client(timeout=20) as client:
        r = client.post(url, headers=_headers(), params=params, json=body)
    return _handle(r)


def _put(path: str, body: dict, params: Optional[dict] = None) -> dict:
    url = f"{config.GHL_API_BASE}{path}"
    with httpx.Client(timeout=20) as client:
        r = client.put(url, headers=_headers(), params=params, json=body)
    return _handle(r)


def _handle(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        snippet = (r.text or "").strip()
        if len(snippet) > 300:
            snippet = snippet[:300] + "…"
        raise RuntimeError(
            f"GoHighLevel API returned {r.status_code} for {r.request.url.path}. {snippet}"
        )
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {}


# --- Field helpers -----------------------------------------------------------

def _first(d: dict, *keys: str, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _num(v: Any) -> float | int:
    try:
        f = float(v)
        return int(f) if f == int(f) else round(f, 1)
    except (TypeError, ValueError):
        return 0


def _parse_dt(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
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


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# --- Public API calls --------------------------------------------------------

def get_accounts(location_id: str) -> list[dict]:
    """Connected social accounts (pages) for a location."""
    data = _get(f"/social-media-posting/{location_id}/accounts")
    body = data.get("results", data) if isinstance(data, dict) else {}
    return (body.get("accounts") if isinstance(body, dict) else None) or []


def list_posts(location_id: str, limit: int = 100,
               days_back: int = 120, days_forward: int = 45) -> list[dict]:
    """Recent + upcoming posts. All DTO fields must be strings (GHL requirement)."""
    now = datetime.now(timezone.utc)
    body = {
        "type": "all",
        "accounts": "",
        "skip": "0",
        "limit": str(limit),
        "fromDate": _iso(now - timedelta(days=days_back)),
        "toDate": _iso(now + timedelta(days=days_forward)),
        "includeUsers": "true",
    }
    data = _post(f"/social-media-posting/{location_id}/posts/list", body)
    inner = data.get("results", data) if isinstance(data, dict) else {}
    return (inner.get("posts") if isinstance(inner, dict) else None) or []


def get_statistics(location_id: str, profile_ids: list[str],
                   platforms: Optional[list[str]] = None) -> dict:
    """
    Advanced Analytics for the given account profileIds (last 7 days, with a
    change vs the previous 7). Returns the parsed `results` object.
    """
    body: dict = {"profileIds": profile_ids}
    if platforms:
        body["platforms"] = platforms
    data = _post("/social-media-posting/statistics", body, params={"locationId": location_id})
    return data.get("results", data) if isinstance(data, dict) else {}


# --- Owner-friendly aggregation ---------------------------------------------

_PLATFORM_LABELS = {
    "facebook": "Facebook", "instagram": "Instagram", "google": "Google Business",
    "linkedin": "LinkedIn", "twitter": "X (Twitter)", "tiktok": "TikTok",
    "youtube": "YouTube", "pinterest": "Pinterest", "threads": "Threads",
}
# Platforms GHL's statistics API can report on.
_STAT_PLATFORMS = {"facebook", "instagram", "linkedin", "google", "pinterest", "youtube", "tiktok"}


def _platform_label(raw: str) -> str:
    return _PLATFORM_LABELS.get((raw or "").lower(), (raw or "Other").title())


def _metric(breakdowns: dict, totals: dict, name: str) -> dict:
    m = breakdowns.get(name) if isinstance(breakdowns, dict) else None
    m = m or {}
    value = _num(_first(m, "total", default=totals.get(name, 0)))
    change = _num(m.get("totalChange", 0))
    return {"value": value, "change": change}


def _stats_for(location_id: str, account: dict) -> Optional[dict]:
    """Per-page performance metrics, or None if this platform has no analytics."""
    profile_id = _first(account, "profileId", "profileID")
    platform = (_first(account, "platform", default="") or "").lower()
    if not profile_id or platform not in _STAT_PLATFORMS:
        return None
    res = get_statistics(location_id, [str(profile_id)], [platform])
    totals = (res.get("totals") if isinstance(res, dict) else None) or {}
    bd = (res.get("breakdowns") if isinstance(res, dict) else None) or {}
    return {
        "reach": _metric(bd, totals, "reach"),
        "impressions": _metric(bd, totals, "impressions"),
        "engagement": _metric(bd, totals, "engagement"),
        "posts": _num(_first(totals, "posts", default=_first(bd.get("posts", {}), "total", default=0))),
        "followers": _num(totals.get("followers", 0)),
        "likes": _num(totals.get("likes", 0)),
        "comments": _num(totals.get("comments", 0)),
    }


def _post_accounts(post: dict) -> list[str]:
    val = _first(post, "accountIds", "accounts", "socialAccountIds", default=[])
    if isinstance(val, str):
        return [v.strip() for v in val.split(",") if v.strip()]
    out = []
    for item in val or []:
        out.append(str(_first(item, "id", "_id", default="")) if isinstance(item, dict) else str(item))
    return [i for i in out if i]


def _post_time(post: dict) -> Optional[datetime]:
    return _parse_dt(_first(post, "publishedAt", "scheduleDate", "scheduledAt", "createdAt"))


def _is_scheduled(post: dict) -> bool:
    return (_first(post, "status", "state", default="") or "").lower() in (
        "scheduled", "pending", "queued", "in_progress")


def _is_published(post: dict) -> bool:
    return (_first(post, "status", "state", default="") or "").lower() in (
        "published", "posted", "completed", "success", "live")


def _freshness(days_since: Optional[int]) -> str:
    if days_since is None:
        return "none"
    if days_since <= 7:
        return "good"
    if days_since <= 21:
        return "aging"
    return "stale"


def social_overview(now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    locations_out: list[dict] = []
    totals = {"accounts": 0, "reach": 0, "impressions": 0, "engagement": 0,
              "followers": 0, "posts": 0}
    stats_ok = False

    for loc in config.GHL_LOCATIONS:
        loc_id = loc["id"]
        accounts = get_accounts(loc_id)

        # Posting context (last posted / scheduled). Non-fatal if it fails.
        by_account: dict[str, list[dict]] = {}
        try:
            for p in list_posts(loc_id):
                for aid in _post_accounts(p):
                    by_account.setdefault(aid, []).append(p)
        except Exception:  # noqa: BLE001
            by_account = {}

        rows = []
        for a in accounts:
            if _first(a, "deleted", default=False) is True:
                continue
            aid = str(_first(a, "id", "_id", default=""))
            name = _first(a, "name", "accountName", default="Unnamed page")
            platform = _platform_label(_first(a, "platform", default=""))
            avatar = _first(a, "avatar", "picture", default="")

            try:
                perf = _stats_for(loc_id, a)
            except Exception:  # noqa: BLE001
                perf = None
            if perf:
                stats_ok = True
                totals["reach"] += perf["reach"]["value"]
                totals["impressions"] += perf["impressions"]["value"]
                totals["engagement"] += perf["engagement"]["value"]
                totals["followers"] += perf["followers"]
                totals["posts"] += perf["posts"]

            aposts = by_account.get(aid, [])
            pub_times = [t for t in (_post_time(p) for p in aposts if _is_published(p)) if t]
            sched = [t for t in (_post_time(p) for p in aposts if _is_scheduled(p)) if t and t >= now]
            last_post = max(pub_times) if pub_times else None
            days_since = (now - last_post).days if last_post else None

            rows.append({
                "name": name,
                "platform": platform,
                "platform_key": (_first(a, "platform", default="") or "").lower(),
                "avatar": avatar,
                "perf": perf,
                "expired": _first(a, "isExpired", default=False) is True,
                "last_post_at": last_post.strftime("%b %-d, %Y") if last_post else None,
                "days_since": days_since,
                "freshness": _freshness(days_since),
                "scheduled": len(sched),
                "next_scheduled_at": min(sched).strftime("%b %-d, %Y") if sched else None,
            })
            totals["accounts"] += 1

        rows.sort(key=lambda r: (r["platform"], r["name"]))
        locations_out.append({"label": loc["label"] or f"Location {loc_id[:6]}", "accounts": rows})

    return {
        "locations": locations_out,
        "totals": totals,
        "stats_ok": stats_ok,
        "window": "Last 7 days vs previous 7",
        "generated_at": now.strftime("%b %-d, %Y at %-I:%M %p UTC"),
    }


# --- Diagnostics -------------------------------------------------------------

_REDACT_RE = re.compile(r"token|secret|password|api[_-]?key|access|refresh", re.I)


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if _REDACT_RE.search(k) else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


# --- Contacts & workflows (appointment reminders) ----------------------------

def upsert_contact(location_id: str, name: str, email: Optional[str] = None,
                   phone: Optional[str] = None, tags: Optional[list[str]] = None) -> dict:
    """
    Create or update a contact (matched by email/phone) and return its record.
    Uses POST /contacts/upsert so re-scheduling the same person doesn't duplicate.
    """
    name = (name or "").strip()
    first, _, last = name.partition(" ")
    body: dict = {"locationId": location_id, "name": name or (email or phone or "Contact")}
    if first:
        body["firstName"] = first
    if last:
        body["lastName"] = last
    if email:
        body["email"] = email.strip()
    if phone:
        body["phone"] = phone.strip()
    if tags:
        body["tags"] = tags
    data = _post("/contacts/upsert", body)
    contact = data.get("contact") if isinstance(data, dict) else None
    contact = contact if isinstance(contact, dict) else (data if isinstance(data, dict) else {})
    cid = _first(contact, "id", "_id", "contactId")
    if not cid:
        raise RuntimeError(f"GoHighLevel did not return a contact id. Response: {str(data)[:200]}")
    return {"id": str(cid), "raw": contact}


def search_contacts(location_id: str, query: str, limit: int = 10) -> list[dict]:
    """Look up contacts by name/email/phone — used for the lookup + Chrome extension."""
    data = _get("/contacts/", params={"locationId": location_id,
                                       "query": (query or "").strip(), "limit": limit})
    rows = (data.get("contacts") if isinstance(data, dict) else None) or []
    out = []
    for c in rows:
        out.append({
            "id": str(_first(c, "id", "_id", default="")),
            "name": _first(c, "contactName", "name",
                           default=f"{_first(c, 'firstName', default='') or ''} "
                                   f"{_first(c, 'lastName', default='') or ''}".strip()),
            "email": _first(c, "email", default=""),
            "phone": _first(c, "phone", default=""),
        })
    return out


def list_workflows(location_id: str) -> list[dict]:
    """All workflows for a location (id + name), for the reminder mapping page."""
    data = _get("/workflows/", params={"locationId": location_id})
    rows = (data.get("workflows") if isinstance(data, dict) else None) or []
    return [{"id": str(_first(w, "id", "_id", default="")),
             "name": _first(w, "name", default="(unnamed workflow)"),
             "status": _first(w, "status", default="")} for w in rows
            if _first(w, "id", "_id")]


def add_contact_to_workflow(contact_id: str, workflow_id: str,
                            event_start_time: Optional[str] = None) -> dict:
    """
    Drop a contact into a workflow. event_start_time (ISO8601 with offset) sets
    the workflow's appointment/event reference so reminder timing works.
    """
    body: dict = {}
    if event_start_time:
        body["eventStartTime"] = event_start_time
    return _post(f"/contacts/{contact_id}/workflow/{workflow_id}", body)


def list_calendars(location_id: str) -> list[dict]:
    """All calendars for a location (id + name), for the reminder mapping page."""
    data = _get("/calendars/", params={"locationId": location_id})
    rows = (data.get("calendars") if isinstance(data, dict) else None) or []
    return [{"id": str(_first(c, "id", "_id", default="")),
             "name": _first(c, "name", default="(unnamed calendar)")} for c in rows
            if _first(c, "id", "_id")]


def create_appointment(location_id: str, calendar_id: str, contact_id: str,
                       start_time: str, end_time: str, title: Optional[str] = None,
                       notify: bool = False) -> dict:
    """
    Book an appointment on the contact's record. start_time/end_time are ISO8601
    with the clinic's UTC offset. notify=False leaves reminders to the workflow.
    """
    body: dict = {
        "calendarId": calendar_id,
        "locationId": location_id,
        "contactId": contact_id,
        "startTime": start_time,
        "endTime": end_time,
        "appointmentStatus": "confirmed",
        "ignoreFreeSlotValidation": True,   # book the exact time we were given
        "toNotify": notify,
    }
    if title:
        body["title"] = title
    data = _post("/calendars/events/appointments", body)
    aid = _first(data, "id", "_id", "appointmentId", "eventId") if isinstance(data, dict) else None
    return {"id": str(aid) if aid else "", "raw": data}


def get_contact(contact_id: str) -> dict:
    """Full contact record, normalized for the client detail page."""
    data = _get(f"/contacts/{contact_id}")
    c = data.get("contact") if isinstance(data, dict) else None
    c = c if isinstance(c, dict) else (data if isinstance(data, dict) else {})
    name = _first(c, "contactName", "name") or \
        f"{_first(c, 'firstName', default='') or ''} {_first(c, 'lastName', default='') or ''}".strip()
    addr = ", ".join(str(p) for p in [
        _first(c, "address1"), _first(c, "city"), _first(c, "state"),
        _first(c, "postalCode"), _first(c, "country"),
    ] if p)
    tags = c.get("tags") if isinstance(c.get("tags"), list) else []
    return {
        "id": str(_first(c, "id", "_id", default=contact_id)),
        "name": name or "(no name)",
        "first": _first(c, "firstName", default=""),
        "last": _first(c, "lastName", default=""),
        "email": _first(c, "email", default=""),
        "phone": _first(c, "phone", default=""),
        "address1": _first(c, "address1", default=""),
        "city": _first(c, "city", default=""),
        "state": _first(c, "state", default=""),
        "postal": _first(c, "postalCode", default=""),
        "country": _first(c, "country", default=""),
        "address": addr,
        "tags": [str(t) for t in tags],
        "created": _first(c, "dateAdded", "createdAt", default=""),
        "source": _first(c, "source", default=""),
    }


def update_contact(contact_id: str, fields: dict) -> dict:
    """Update a contact's details. Only non-None fields are sent."""
    body = {k: v for k, v in fields.items() if v is not None}
    return _put(f"/contacts/{contact_id}", body)


def list_contact_notes(contact_id: str) -> list[dict]:
    """A contact's notes, newest first."""
    data = _get(f"/contacts/{contact_id}/notes")
    rows = (data.get("notes") if isinstance(data, dict) else None) or []
    out = [{"id": str(_first(n, "id", "_id", default="")),
            "body": _first(n, "body", default=""),
            "created": _first(n, "dateAdded", "createdAt", default="")} for n in rows]
    out.sort(key=lambda n: n["created"] or "", reverse=True)
    return out


def add_contact_note(contact_id: str, body: str, user_id: Optional[str] = None) -> dict:
    """Add a note to a contact's record."""
    payload: dict = {"body": body}
    if user_id:
        payload["userId"] = user_id
    return _post(f"/contacts/{contact_id}/notes", payload)


def get_contact_appointments(contact_id: str) -> list[dict]:
    """A contact's appointments from GoHighLevel, newest first."""
    data = _get(f"/contacts/{contact_id}/appointments")
    rows = (data.get("events") if isinstance(data, dict) else None)
    if rows is None and isinstance(data, dict):
        rows = data.get("appointments")
    rows = rows or []
    out = [{"id": str(_first(e, "id", "_id", default="")),
            "title": _first(e, "title", default=""),
            "start": _first(e, "startTime", "startAt", default=""),
            "end": _first(e, "endTime", "endAt", default=""),
            "status": _first(e, "appointmentStatus", "status", default="")} for e in rows]
    out.sort(key=lambda e: e["start"] or "", reverse=True)
    return out


def clients_debug(contact_id: str) -> dict:
    """Credential-redacted contact/notes/appointments dump, for /clients/{id}?debug=1."""
    out: dict = {"contact_id": contact_id}
    for label, fn in (("contact", lambda: _get(f"/contacts/{contact_id}")),
                      ("notes", lambda: _get(f"/contacts/{contact_id}/notes")),
                      ("appointments", lambda: _get(f"/contacts/{contact_id}/appointments"))):
        try:
            out[f"{label}_raw"] = _redact(fn())
        except Exception as exc:  # noqa: BLE001
            out[f"{label}_error"] = str(exc)
    return out


def reminders_debug(location_id: str, sample_query: str = "a") -> dict:
    """Credential-redacted raw contact/workflow responses, for /reminders/settings?debug=1."""
    out: dict = {"location_id": location_id}
    try:
        out["workflows_raw"] = _redact(_get("/workflows/", params={"locationId": location_id}))
    except Exception as exc:  # noqa: BLE001
        out["workflows_error"] = str(exc)
    try:
        out["contacts_search_raw"] = _redact(
            _get("/contacts/", params={"locationId": location_id, "query": sample_query, "limit": 2})
        )
    except Exception as exc:  # noqa: BLE001
        out["contacts_search_error"] = str(exc)
    try:
        out["calendars_raw"] = _redact(_get("/calendars/", params={"locationId": location_id}))
    except Exception as exc:  # noqa: BLE001
        out["calendars_error"] = str(exc)
    return out


def raw_debug() -> list[dict]:
    """Credential-redacted raw API responses, for /social?debug=1."""
    out: list[dict] = []
    for loc in config.GHL_LOCATIONS:
        lid = loc["id"]
        entry: dict = {"location": loc}
        profile_ids, platforms = [], set()
        try:
            accts = get_accounts(lid)
            entry["accounts_raw"] = _redact({"count": len(accts), "accounts": accts})
            for a in accts:
                pid = _first(a, "profileId")
                plat = (_first(a, "platform", default="") or "").lower()
                if pid and plat in _STAT_PLATFORMS:
                    profile_ids.append(str(pid))
                    platforms.add(plat)
        except Exception as exc:  # noqa: BLE001
            entry["accounts_error"] = str(exc)
        try:
            entry["statistics_raw"] = _redact(
                _post("/social-media-posting/statistics",
                      {"profileIds": profile_ids, "platforms": list(platforms)},
                      params={"locationId": lid})
            )
        except Exception as exc:  # noqa: BLE001
            entry["statistics_error"] = str(exc)
        try:
            entry["posts_raw"] = _redact({"posts": list_posts(lid, limit=3)[:3]})
        except Exception as exc:  # noqa: BLE001
            entry["posts_error"] = str(exc)
        out.append(entry)
    return out
