"""
config.py — central settings and the permission (roles) rules.

Everything configurable lives in the .env file; this module reads it and also
defines the three access levels and what each one can do. As we add features
later, we mostly just add new capability names here and grant them to roles.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Basic app settings ------------------------------------------------------
# The public web address of the dashboard (the secure Cloudflare Tunnel URL).
# Used to build the Google login redirect. Example: https://spa.example.com
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")

# Secret used to sign login cookies. Set a long random value in .env.
SESSION_SECRET = os.environ.get("SESSION_SECRET", "change-me-please")

# Allow logins from this Google Workspace domain (e.g. "vmedical.ca"). You can
# list more than one, separated by commas. Leave blank to allow any Google
# account (not recommended for production).
_domains_raw = os.environ.get("ALLOWED_EMAIL_DOMAIN", "").strip().lower()
ALLOWED_EMAIL_DOMAINS = [d.strip() for d in _domains_raw.split(",") if d.strip()]

# Extra individual emails that are always allowed even if their domain isn't in
# the list above — handy for an outside admin/consultant. Comma-separated.
_extra_raw = os.environ.get("EXTRA_ALLOWED_EMAILS", "").strip().lower()
EXTRA_ALLOWED_EMAILS = [e.strip() for e in _extra_raw.split(",") if e.strip()]

# The email that should automatically be the Super Admin on first login. This
# email is always allowed to sign in, even if its domain isn't listed above.
SUPER_ADMIN_EMAIL = os.environ.get("SUPER_ADMIN_EMAIL", "").strip().lower()

# Google OAuth credentials (from Google Cloud Console).
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

# Optional shared secret so only GoHighLevel can post to the call webhook.
GHL_WEBHOOK_SECRET = os.environ.get("GHL_WEBHOOK_SECRET", "").strip()

# --- GoHighLevel social metrics (Social Planner API) -------------------------
# A sub-account Private Integration Token (GHL -> Settings -> Private
# Integrations) with the read-only Social Planner scopes
# ("View Social Planner Accounts" + "View Social Planner Posts"). Leave blank
# to keep the Social tab in its "not connected yet" setup state.
GHL_API_TOKEN = os.environ.get("GHL_API_TOKEN", "").strip()
GHL_API_BASE = os.environ.get(
    "GHL_API_BASE", "https://services.leadconnectorhq.com"
).rstrip("/")
GHL_API_VERSION = os.environ.get("GHL_API_VERSION", "2021-07-28").strip()

# One or more GHL location (sub-account) ids whose social pages to show.
# Optionally label each so the dashboard reads nicely. Comma-separated:
#   GHL_LOCATIONS=abc123def456
#   GHL_LOCATIONS=Kentville=abc123,New Minas=def456
_locs_raw = os.environ.get("GHL_LOCATIONS", "").strip()
GHL_LOCATIONS: list[dict] = []
for _part in _locs_raw.split(","):
    _part = _part.strip()
    if not _part:
        continue
    if "=" in _part:
        _label, _lid = _part.split("=", 1)
        GHL_LOCATIONS.append({"label": _label.strip(), "id": _lid.strip()})
    else:
        GHL_LOCATIONS.append({"label": "", "id": _part})


def ghl_social_enabled() -> bool:
    """True once a token and at least one location id are configured."""
    return bool(GHL_API_TOKEN and GHL_LOCATIONS)

# --- Email monitor (reads the "AI Call Recap" emails) ------------------------
# The app checks this mailbox on a schedule and turns each new recap email into
# a dashboard message + Obsidian note. Leave IMAP_USER/IMAP_PASSWORD blank to
# turn the email monitor off.
IMAP_HOST = os.environ.get("IMAP_HOST", "imap.gmail.com").strip()
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993") or "993")
IMAP_USER = os.environ.get("IMAP_USER", "").strip()
IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD", "").replace(" ", "").strip()
# Only emails from this sender with this subject prefix are treated as recaps.
RECAP_FROM = os.environ.get("RECAP_FROM", "reply@c.clientconnector.app").strip().lower()
RECAP_SUBJECT_PREFIX = os.environ.get("RECAP_SUBJECT_PREFIX", "AI Call Recap").strip()
# How often to check the inbox, in seconds.
EMAIL_POLL_SECONDS = int(os.environ.get("EMAIL_POLL_SECONDS", "60") or "60")


def email_monitor_enabled() -> bool:
    return bool(IMAP_USER and IMAP_PASSWORD)

# --- Roles and permissions ---------------------------------------------------
# The three access levels, highest to lowest.
ROLES = ["super_admin", "spa_manager", "team_member"]
ROLE_LABELS = {
    "super_admin": "Super Admin",
    "spa_manager": "Spa Manager",
    "team_member": "Team Member",
}
DEFAULT_ROLE = "team_member"

# Capabilities = the individual things a person can do. Add to this list as the
# platform grows; then grant them to roles in ROLE_CAPABILITIES below.
#   view_messages     - see the after-hours phone message inbox
#   respond_messages  - mark a message as responded
#   manage_users      - invite/remove team members and change their roles
#   manage_settings   - change system settings (future)
#   view_social       - see the social-media posting-activity dashboard
ROLE_CAPABILITIES = {
    "super_admin": {
        "view_messages",
        "respond_messages",
        "manage_users",
        "manage_settings",
        "view_social",
    },
    "spa_manager": {
        "view_messages",
        "respond_messages",
        "manage_users",  # managers can manage team members (but not super admins)
        "view_social",
    },
    "team_member": {
        "view_messages",
        "respond_messages",
    },
}


def can(role: str, capability: str) -> bool:
    """True if the given role is allowed to do the given thing."""
    return capability in ROLE_CAPABILITIES.get(role, set())
