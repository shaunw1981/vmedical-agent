"""
google_business.py — read (and reply to) Google reviews straight from Google.

Uses the Google Business Profile APIs:
  • OAuth 2.0 (scope business.manage) — a one-time "Connect Google Business"
    grant from the profile owner; we keep the refresh token in the settings
    table so the connection survives restarts.
  • Account/location discovery (My Business Account Management + Business
    Information v1) to find which profile to read.
  • Reviews (My Business v4)  GET  .../reviews
  • Reply   (My Business v4)  PUT  .../reviews/{id}/reply   {comment}

Google gates the v4 reviews API: the Cloud project must be approved for the
Business Profile API before these calls return data (otherwise 403). See
SETUP notes / .env.example.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx

import config
import db
import reviews_common

SCOPE = "https://www.googleapis.com/auth/business.manage"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
_INFO_BASE = "https://mybusinessbusinessinformation.googleapis.com/v1"
_V4_BASE = "https://mybusiness.googleapis.com/v4"

_STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}

_RT_KEY = "gbp_refresh_token"
_PARENT_KEY = "gbp_parent"  # "accounts/{id}/locations/{id}"


# --- Connection state --------------------------------------------------------
def enabled() -> bool:
    """The OAuth app exists, so a Connect flow is possible."""
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def is_connected() -> bool:
    """A profile owner has authorized us and we hold a refresh token."""
    return bool(db.get_setting(_RT_KEY))


def disconnect() -> None:
    db.delete_setting(_RT_KEY)
    db.delete_setting(_PARENT_KEY)


# --- OAuth -------------------------------------------------------------------
def auth_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",     # ask for a refresh token
        "prompt": "consent",          # force refresh_token even on re-auth
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str, redirect_uri: str) -> None:
    """Trade the auth code for tokens and persist the refresh token."""
    with httpx.Client(timeout=20) as client:
        r = client.post(_TOKEN_URL, data={
            "code": code,
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
    if r.status_code >= 400:
        raise RuntimeError(f"Google token exchange failed ({r.status_code}): {r.text[:300]}")
    data = r.json()
    refresh = data.get("refresh_token")
    if not refresh:
        raise RuntimeError(
            "Google didn't return a refresh token. Remove this app's access at "
            "myaccount.google.com/permissions and connect again.")
    db.set_setting(_RT_KEY, refresh)


def _access_token() -> str:
    refresh = db.get_setting(_RT_KEY)
    if not refresh:
        raise RuntimeError("Google Business isn't connected yet.")
    with httpx.Client(timeout=20) as client:
        r = client.post(_TOKEN_URL, data={
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        })
    if r.status_code >= 400:
        raise RuntimeError(f"Couldn't refresh Google token ({r.status_code}): {r.text[:300]}")
    return r.json()["access_token"]


# --- HTTP helpers ------------------------------------------------------------
def _get(url: str, token: str, params: Optional[dict] = None) -> dict:
    with httpx.Client(timeout=25) as client:
        r = client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
    if r.status_code >= 400:
        raise RuntimeError(f"Google API {r.status_code} for {url.rsplit('/', 2)[-1]}: {r.text[:300]}")
    return r.json() if r.content else {}


def _parse_time(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


# --- Discovery ---------------------------------------------------------------
def _parent(token: str) -> str:
    """The 'accounts/{a}/locations/{l}' to read reviews from (cached)."""
    cached = db.get_setting(_PARENT_KEY)
    if cached:
        return cached
    acct = (config.GOOGLE_BUSINESS_ACCOUNT or "").strip()
    loc = (config.GOOGLE_BUSINESS_LOCATION or "").strip()
    if not acct:
        accounts = _get(_ACCOUNTS_URL, token).get("accounts") or []
        if not accounts:
            raise RuntimeError("No Google Business accounts found for this Google login.")
        acct = accounts[0]["name"].split("/")[-1]
    if not loc:
        locs = _get(f"{_INFO_BASE}/accounts/{acct}/locations", token,
                    {"readMask": "name,title", "pageSize": 100}).get("locations") or []
        if not locs:
            raise RuntimeError("No Google Business locations found for this account.")
        loc = locs[0]["name"].split("/")[-1]
    parent = f"accounts/{acct}/locations/{loc}"
    db.set_setting(_PARENT_KEY, parent)
    return parent


# --- Reviews -----------------------------------------------------------------
def _norm(r: dict, parent: str) -> dict:
    reviewer = (r.get("reviewer") or {}).get("displayName") or "Anonymous"
    text = r.get("comment") or ""
    dt = _parse_time(r.get("createTime"))
    reply = (r.get("reviewReply") or {}).get("comment") or ""
    return {
        "id": r.get("reviewId") or "",
        "reviewer": reviewer.strip() or "Anonymous",
        "rating": _STARS.get(r.get("starRating", ""), 0),
        "text": text.strip(),
        "source_key": "google",
        "source": "Google",
        "date": dt.strftime("%b %-d, %Y") if dt else None,
        "_sort": dt or datetime.min.replace(tzinfo=timezone.utc),
        "replied": bool(reply),
        "reply": reply.strip(),
        "location_id": parent,
    }


def _fetch_reviews(token: str, parent: str, max_reviews: int = 200) -> list[dict]:
    out: list[dict] = []
    page_token = None
    while len(out) < max_reviews:
        params = {"pageSize": 50, "orderBy": "updateTime desc"}
        if page_token:
            params["pageToken"] = page_token
        data = _get(f"{_V4_BASE}/{parent}/reviews", token, params)
        out.extend(data.get("reviews") or [])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return out[:max_reviews]


def reviews_overview(now: Optional[datetime] = None, max_reviews: int = 200) -> dict:
    now = now or datetime.now(timezone.utc)
    token = _access_token()
    parent = _parent(token)
    raw = _fetch_reviews(token, parent, max_reviews)
    normalized = [_norm(r, parent) for r in raw]
    return reviews_common.aggregate(normalized, now, sampled=len(raw) >= max_reviews)


def reply_to_review(review_id: str, parent: str, text: str) -> dict:
    review_id = (review_id or "").strip()
    if not review_id:
        raise ValueError("Missing review id — can't post a reply.")
    token = _access_token()
    url = f"{_V4_BASE}/{parent}/reviews/{review_id}/reply"
    with httpx.Client(timeout=25) as client:
        r = client.put(url, headers={"Authorization": f"Bearer {token}"}, json={"comment": text})
    if r.status_code >= 400:
        raise RuntimeError(f"Google API {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


def debug() -> dict:
    """Connection diagnostic for /reviews?debug=1 (no secrets returned)."""
    info: dict = {"enabled": enabled(), "connected": is_connected(),
                  "parent": db.get_setting(_PARENT_KEY)}
    if is_connected():
        try:
            token = _access_token()
            info["token_refresh"] = "ok"
            info["parent"] = _parent(token)
            data = _get(f"{_V4_BASE}/{info['parent']}/reviews", token, {"pageSize": 3})
            info["sample_count"] = len(data.get("reviews") or [])
            info["averageRating"] = data.get("averageRating")
            info["totalReviewCount"] = data.get("totalReviewCount")
        except Exception as exc:  # noqa: BLE001
            info["error"] = str(exc)
    return info
