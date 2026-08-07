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


# --- Reviews (Reputation) ----------------------------------------------------
# Google + Facebook reviews sync into GoHighLevel's Reputation manager and are
# read back here with the same Private Integration Token (add the read-only
# "View Reviews" reputation scope to it). Field names vary a little across GHL
# API versions, so parsing stays deliberately tolerant (_first with aliases);
# /reviews?debug=1 dumps the raw shape so mappings can be confirmed on connect.

_REVIEW_SOURCE_LABELS = {
    "google": "Google", "facebook": "Facebook", "yelp": "Yelp",
    "gmb": "Google", "google_my_business": "Google",
}


def get_reviews(location_id: str, limit: int = 100,
                review_type: Optional[str] = None) -> list[dict]:
    """Recent reviews for a location, newest first."""
    params = {
        "locationId": location_id,
        "limit": str(limit),
        "sortBy": "reviewDate",
        "sortOrder": "desc",
    }
    if review_type:
        params["type"] = review_type
    data = _get("/reputation/reviews", params=params)
    if isinstance(data, dict):
        body = data.get("reviews", data.get("data", data.get("results")))
        if isinstance(body, dict):
            body = body.get("reviews", body.get("data"))
        return body if isinstance(body, list) else []
    return data if isinstance(data, list) else []


def _review_source_label(raw: str) -> str:
    key = (raw or "").lower()
    return _REVIEW_SOURCE_LABELS.get(key, (raw or "Review").title())


def _norm_review(r: dict) -> dict:
    """Flatten one raw review into the fields the template needs."""
    try:
        rating = int(round(float(_first(r, "rating", "reviewRating", "stars", default=0) or 0)))
    except (TypeError, ValueError):
        rating = 0
    rating = max(0, min(5, rating))

    reviewer = _first(r, "reviewer", "reviewerName", "name", "userName", "author", default="")
    if isinstance(reviewer, dict):
        reviewer = _first(reviewer, "name", "displayName", "firstName", default="")
    text = _first(r, "comment", "content", "reviewComment", "reviewBody", "text", "review", default="")

    src_key = (_first(r, "platform", "source", "type", "provider", default="") or "").lower()
    dt = _parse_dt(_first(r, "reviewDate", "dateAdded", "createdAt", "date", "updatedAt"))

    reply = _first(r, "reply", "replyComment", "response", "reviewReply", default="")
    if isinstance(reply, dict):
        reply = _first(reply, "comment", "content", "text", default="")
    replied_flag = _first(r, "replied", "isReplied", "hasReply", default=None)
    status = (_first(r, "status", default="") or "").lower()
    replied = bool(reply) or replied_flag is True or status == "replied"

    return {
        "reviewer": (reviewer or "Anonymous").strip() or "Anonymous",
        "rating": rating,
        "text": (text or "").strip(),
        "source_key": src_key or "other",
        "source": _review_source_label(src_key) if src_key else "Review",
        "date": dt.strftime("%b %-d, %Y") if dt else None,
        "_sort": dt or datetime.min.replace(tzinfo=timezone.utc),
        "replied": replied,
        "reply": (reply or "").strip(),
    }


def reviews_overview(now: Optional[datetime] = None,
                     per_location_limit: int = 200) -> dict:
    """Aggregate reviews across all configured locations for the Reviews page."""
    now = now or datetime.now(timezone.utc)
    all_reviews: list[dict] = []
    for loc in config.GHL_LOCATIONS:
        for raw in get_reviews(loc["id"], limit=per_location_limit):
            nr = _norm_review(raw)
            nr["location"] = loc["label"] or ""
            all_reviews.append(nr)

    all_reviews.sort(key=lambda r: r["_sort"], reverse=True)
    rated = [r for r in all_reviews if r["rating"] > 0]
    count = len(all_reviews)
    average = round(sum(r["rating"] for r in rated) / len(rated), 1) if rated else 0.0

    distribution = {s: 0 for s in (5, 4, 3, 2, 1)}
    for r in rated:
        distribution[r["rating"]] += 1

    sources: dict[str, int] = {}
    for r in all_reviews:
        sources[r["source"]] = sources.get(r["source"], 0) + 1

    unreplied = sum(1 for r in all_reviews if not r["replied"])
    since = now - timedelta(days=30)
    recent_30 = sum(1 for r in all_reviews if r["_sort"] >= since)
    capped = per_location_limit * max(1, len(config.GHL_LOCATIONS))

    return {
        "totals": {
            "count": count,
            "average": average,
            "average_rounded": int(round(average)),
            "rated": len(rated),
            "unreplied": unreplied,
            "replied": count - unreplied,
            "sources": sources,
            "distribution": distribution,
            "recent_30": recent_30,
        },
        "recent": all_reviews[:12],
        "sampled": count >= capped,
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


def reviews_raw_debug() -> list[dict]:
    """Credential-redacted raw reviews responses, for /reviews?debug=1."""
    out: list[dict] = []
    for loc in config.GHL_LOCATIONS:
        entry: dict = {"location": loc}
        try:
            entry["reviews_raw"] = _redact(
                _get("/reputation/reviews",
                     params={"locationId": loc["id"], "limit": "5",
                             "sortBy": "reviewDate", "sortOrder": "desc"})
            )
        except Exception as exc:  # noqa: BLE001
            entry["reviews_error"] = str(exc)
        out.append(entry)
    return out
