"""
ghl.py — reads social-media posting activity from GoHighLevel.

GoHighLevel's public API only exposes the *Social Planner* (publishing) data:
which accounts are connected, and the posts you've published/scheduled through
GHL. It does NOT expose native platform analytics — reach, impressions,
follower counts, post likes/comments, or Google review ratings. Those live in
Facebook's and Google's own APIs and would be a separate integration.

So this module turns "posting activity" into numbers a business owner cares
about: are we consistently showing up on each page, what's queued to go out,
and did anything fail to post.

Auth: a sub-account **Private Integration Token** (GHL → Settings → Private
Integrations) with the read-only Social Planner scopes. Configure it, the API
base, and the location id(s) in .env — see config.py / .env.example.
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


def _get(path: str) -> dict:
    url = f"{config.GHL_API_BASE}{path}"
    with httpx.Client(timeout=20) as client:
        r = client.get(url, headers=_headers())
    return _handle(r)


def _post(path: str, body: dict) -> dict:
    url = f"{config.GHL_API_BASE}{path}"
    with httpx.Client(timeout=20) as client:
        r = client.post(url, headers=_headers(), json=body)
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


# --- Field helpers (GHL field names vary, so read them tolerantly) -----------

def _first(d: dict, *keys: str, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 / epoch-millis timestamp into an aware UTC datetime."""
    if value in (None, ""):
        return None
    # Epoch milliseconds (int or numeric string).
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


# --- Public API calls --------------------------------------------------------

def get_accounts(location_id: str) -> list[dict]:
    """Connected social accounts (pages) for a location."""
    data = _get(f"/social-media-posting/{location_id}/accounts")
    body = data.get("results", data) if isinstance(data, dict) else {}
    accounts = body.get("accounts") if isinstance(body, dict) else None
    return accounts or []


def list_posts(location_id: str, limit: int = 200) -> list[dict]:
    """Recent posts for a location (across all its connected accounts)."""
    body = {"type": "all", "accounts": [], "skip": 0, "limit": limit}
    data = _post(f"/social-media-posting/{location_id}/posts/list", body)
    inner = data.get("results", data) if isinstance(data, dict) else {}
    posts = inner.get("posts") if isinstance(inner, dict) else None
    return posts or []


def get_statistics(
    location_id: str,
    account_ids: list[str],
    current: Optional[dict] = None,
    previous: Optional[dict] = None,
) -> dict:
    """
    Advanced Analytics for a location's accounts (reach, impressions, followers,
    likes, comments, shares). `current`/`previous` are {"startDate","endDate"}
    ranges; GHL defaults to the last 7 days vs. the previous 7 if omitted.

    NOTE: the exact request/response schema is confirmed on first live call via
    the diagnostic view (see raw_debug); the metric mapping is finalised then.
    """
    body: dict = {"accounts": account_ids}
    if current:
        body["currentRange"] = current
    if previous:
        body["prevRange"] = previous
    return _post(f"/social-media-posting/{location_id}/statistics/", body)


# --- Diagnostics -------------------------------------------------------------

_REDACT_RE = re.compile(r"token|secret|password|api[_-]?key|access|refresh", re.I)


def _redact(obj: Any) -> Any:
    """Strip anything that looks like a credential before we ever display it."""
    if isinstance(obj, dict):
        return {k: ("***" if _REDACT_RE.search(k) else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


def raw_debug() -> list[dict]:
    """
    Return the raw (credential-redacted) API responses for each location so the
    exact field shapes can be confirmed. Used by the /social?debug=1 view.
    """
    out: list[dict] = []
    for loc in config.GHL_LOCATIONS:
        lid = loc["id"]
        entry: dict = {"location": loc}
        try:
            entry["accounts_raw"] = _redact(_get(f"/social-media-posting/{lid}/accounts"))
        except Exception as exc:  # noqa: BLE001
            entry["accounts_error"] = str(exc)
        try:
            entry["posts_raw"] = _redact(_post(
                f"/social-media-posting/{lid}/posts/list",
                {"type": "all", "accounts": [], "skip": 0, "limit": 3},
            ))
        except Exception as exc:  # noqa: BLE001
            entry["posts_error"] = str(exc)
        acct_ids: list[str] = []
        try:
            for a in get_accounts(lid):
                aid = str(_first(a, "id", "_id", "accountId", default=""))
                if aid:
                    acct_ids.append(aid)
        except Exception:  # noqa: BLE001
            pass
        try:
            entry["statistics_raw"] = _redact(get_statistics(lid, acct_ids))
        except Exception as exc:  # noqa: BLE001
            entry["statistics_error"] = str(exc)
        out.append(entry)
    return out


# --- Owner-friendly aggregation ---------------------------------------------

_PLATFORM_LABELS = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "google": "Google Business",
    "gmb": "Google Business",
    "googlemybusiness": "Google Business",
    "linkedin": "LinkedIn",
    "twitter": "X (Twitter)",
    "x": "X (Twitter)",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "pinterest": "Pinterest",
    "threads": "Threads",
}


def _platform_label(raw: str) -> str:
    key = (raw or "").lower().replace(" ", "").replace("-", "").replace("_", "")
    return _PLATFORM_LABELS.get(key, (raw or "Other").title())


def _post_accounts(post: dict) -> list[str]:
    """The account ids a post targeted, however GHL labelled the field."""
    val = _first(post, "accountIds", "accounts", "socialAccountIds", "targetAccounts", default=[])
    ids = []
    for item in val or []:
        if isinstance(item, dict):
            ids.append(str(_first(item, "id", "_id", "accountId", default="")))
        else:
            ids.append(str(item))
    return [i for i in ids if i]


def _classify(post: dict) -> str:
    """Bucket a post as published / scheduled / failed / other."""
    status = (_first(post, "status", "state", default="") or "").lower()
    if status in ("published", "posted", "completed", "success", "live"):
        return "published"
    if status in ("failed", "error", "errored"):
        return "failed"
    if status in ("scheduled", "pending", "queued", "in_progress"):
        return "scheduled"
    return status or "other"


def _post_time(post: dict) -> Optional[datetime]:
    return _parse_dt(_first(
        post, "publishedAt", "publishedDate", "scheduleDate", "scheduledAt",
        "createdAt", "updatedAt",
    ))


def social_overview(now: Optional[datetime] = None) -> dict:
    """
    Pull every configured location and summarise posting activity into a shape
    the Social tab can render directly.
    """
    now = now or datetime.now(timezone.utc)
    cutoff_30 = now - timedelta(days=30)
    cutoff_7 = now - timedelta(days=7)
    week_starts = [now - timedelta(days=7 * (i + 1)) for i in range(8)][::-1]

    locations_out: list[dict] = []
    totals = {"accounts": 0, "posts_30d": 0, "scheduled": 0, "failed_30d": 0}
    weekly_all = [0] * 8

    for loc in config.GHL_LOCATIONS:
        loc_id = loc["id"]
        accounts = get_accounts(loc_id)
        posts = list_posts(loc_id)

        # Index posts by the account they targeted.
        by_account: dict[str, list[dict]] = {}
        for p in posts:
            for aid in _post_accounts(p):
                by_account.setdefault(aid, []).append(p)

        acct_rows = []
        for a in accounts:
            aid = str(_first(a, "id", "_id", "accountId", default=""))
            name = _first(a, "name", "accountName", "pageName", "originName", default="Unnamed page")
            platform = _platform_label(_first(a, "platform", "type", "provider", default=""))
            avatar = _first(a, "avatar", "picture", "profilePicture", "image", default="")
            aposts = by_account.get(aid, [])

            published = [(p, _post_time(p)) for p in aposts if _classify(p) == "published"]
            posts_30d = sum(1 for _, t in published if t and t >= cutoff_30)
            posts_7d = sum(1 for _, t in published if t and t >= cutoff_7)
            failed_30d = sum(
                1 for p in aposts
                if _classify(p) == "failed" and (_post_time(p) or now) >= cutoff_30
            )
            scheduled = [
                (p, _post_time(p)) for p in aposts
                if _classify(p) == "scheduled" and (_post_time(p) or now) >= now
            ]
            published_times = [t for _, t in published if t]
            last_post_at = max(published_times) if published_times else None
            next_times = [t for _, t in scheduled if t]
            next_scheduled_at = min(next_times) if next_times else None

            # 8-week activity histogram for this account.
            weekly = [0] * 8
            for _, t in published:
                if not t:
                    continue
                for i, ws in enumerate(week_starts):
                    we = ws + timedelta(days=7)
                    if ws <= t < we:
                        weekly[i] += 1
                        weekly_all[i] += 1
                        break

            days_since = (now - last_post_at).days if last_post_at else None
            acct_rows.append({
                "name": name,
                "platform": platform,
                "avatar": avatar,
                "posts_30d": posts_30d,
                "posts_7d": posts_7d,
                "failed_30d": failed_30d,
                "scheduled": len(scheduled),
                "last_post_at": last_post_at.strftime("%b %-d, %Y") if last_post_at else None,
                "days_since": days_since,
                "freshness": _freshness(days_since),
                "next_scheduled_at": next_scheduled_at.strftime("%b %-d, %Y") if next_scheduled_at else None,
                "weekly": weekly,
            })
            totals["accounts"] += 1
            totals["posts_30d"] += posts_30d
            totals["scheduled"] += len(scheduled)
            totals["failed_30d"] += failed_30d

        # Sort a location's pages by platform then name for a stable layout.
        acct_rows.sort(key=lambda r: (r["platform"], r["name"]))
        locations_out.append({
            "label": loc["label"] or f"Location {loc_id[:6]}",
            "accounts": acct_rows,
        })

    return {
        "locations": locations_out,
        "totals": totals,
        "weekly": weekly_all,
        "weekly_max": max(weekly_all) if any(weekly_all) else 0,
        "generated_at": now.strftime("%b %-d, %Y at %-I:%M %p UTC"),
    }


def _freshness(days_since: Optional[int]) -> str:
    """A simple health label an owner can read at a glance."""
    if days_since is None:
        return "none"        # never posted (in the window we pulled)
    if days_since <= 7:
        return "good"        # posted within the last week
    if days_since <= 21:
        return "aging"       # getting quiet
    return "stale"           # gone quiet
