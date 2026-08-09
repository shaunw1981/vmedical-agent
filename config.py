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


# --- Appointment reminders ---------------------------------------------------
# The clinic's timezone, used when handing an appointment time to GoHighLevel
# (so "2pm" means 2pm at the clinic, not UTC). Any IANA name works, e.g.
# America/Halifax, America/Toronto, America/Vancouver.
CLINIC_TIMEZONE = os.environ.get("TIMEZONE", "America/Halifax").strip() or "America/Halifax"

# The GHL location (sub-account) that contacts + workflows live in for reminders.
# Defaults to the first GHL_LOCATIONS entry; override with GHL_REMINDER_LOCATION.
_REMINDER_LOCATION = os.environ.get("GHL_REMINDER_LOCATION", "").strip()

# The appointment types the team can pick from. Each drops the contact into the
# matching GoHighLevel workflow (mapped in-app on the Reminder settings page).
# (stable_key, display label) — keys are stored, so don't rename them casually.
APPOINTMENT_TYPES: list[tuple[str, str]] = [
    ("spa_aesthetics_laser", "Spa/Aesthetics/Laser"),
    ("sclerotherapy", "Sclerotherapy"),
    ("evlt", "EVLT"),
    ("consult_dr_davidson", "Consultation Dr Davidson"),
    ("ultrasound", "Ultrasound"),
    ("compression_brace_fitting", "Compression/Brace Fitting"),
]
APPOINTMENT_TYPE_LABELS = dict(APPOINTMENT_TYPES)

# The clinic's actual GoHighLevel workflow for each type. Used as the default
# mapping so reminders work out of the box; can be overridden in-app under
# Reminders → Reminder settings.
DEFAULT_APPOINTMENT_WORKFLOWS = {
    "spa_aesthetics_laser": "cdbad5bf-4259-4f2c-803d-ae76453844d5",
    "sclerotherapy": "e92f01cf-c8f0-439e-b212-08d03d80523f",
    "evlt": "08526574-5694-415b-8638-ffaf89c94fde",
    "consult_dr_davidson": "3df3e2f8-fbc8-4e9b-ae8d-30ff58751bf8",
    "ultrasound": "30e0614e-0c6e-44bf-89bd-8b3c3e8eda0f",
    "compression_brace_fitting": "6ae719b1-9d50-4f85-9757-f195d96db40f",
}

# How long a booked appointment lasts (minutes), used to set its end time when
# we also create the appointment on the contact's GHL record.
APPOINTMENT_DURATION_MINUTES = int(
    os.environ.get("APPOINTMENT_DURATION_MINUTES", "60") or "60"
)

# Optional API key so a future Chrome extension can call the JSON endpoints
# (contact lookup + schedule reminder) without a browser session. Leave blank
# to keep those endpoints session-only.
DASHBOARD_API_KEY = os.environ.get("DASHBOARD_API_KEY", "").strip()


def reminder_location_id() -> str:
    """The GHL sub-account id used for reminder contacts/workflows."""
    if _REMINDER_LOCATION:
        return _REMINDER_LOCATION
    return GHL_LOCATIONS[0]["id"] if GHL_LOCATIONS else ""


def ghl_contacts_enabled() -> bool:
    """True once a token and a reminder location are configured."""
    return bool(GHL_API_TOKEN and reminder_location_id())


# --- Charlie (the AI assistant) ----------------------------------------------
# Charlie answers the team's questions, grounded in the Obsidian knowledge base.
# Needs an Anthropic API key. The model is configurable — claude-opus-5 is the
# most capable; set CHARLIE_MODEL=claude-sonnet-5 for lower cost.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CHARLIE_MODEL = os.environ.get("CHARLIE_MODEL", "claude-opus-5").strip() or "claude-opus-5"
CHARLIE_NAME = os.environ.get("CHARLIE_NAME", "Charlie").strip() or "Charlie"


def charlie_enabled() -> bool:
    return bool(ANTHROPIC_API_KEY)

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

# --- Outgoing email (Charlie sends from this mailbox) ------------------------
# Reuses the same Google account + app password as the email monitor above, so
# no extra credential is needed. Charlie only sends after a human approves.
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com"
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or "587")
SMTP_FROM = os.environ.get("SMTP_FROM", "").strip()  # defaults to IMAP_USER


def email_send_enabled() -> bool:
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
#   manage_settings   - change system settings (e.g. reminder workflow mapping)
#   view_social       - see the social-media posting-activity dashboard
#   view_reminders    - see the scheduled appointment reminders
#   schedule_reminders- look up a contact and schedule an appointment reminder
#   view_clients      - open client records (details, notes, appointment history)
#   use_charlie       - chat with Charlie, the AI assistant
ROLE_CAPABILITIES = {
    "super_admin": {
        "view_messages",
        "respond_messages",
        "manage_users",
        "manage_settings",
        "view_social",
        "view_reminders",
        "schedule_reminders",
        "view_clients",
        "use_charlie",
    },
    "spa_manager": {
        "view_messages",
        "respond_messages",
        "manage_users",  # managers can manage team members (but not super admins)
        "view_social",
        "view_reminders",
        "schedule_reminders",
        "view_clients",
        "use_charlie",
    },
    "team_member": {
        "view_messages",
        "respond_messages",
        "view_reminders",
        "schedule_reminders",
        "view_clients",
        "use_charlie",
    },
}


def can(role: str, capability: str) -> bool:
    """True if the given role is allowed to do the given thing."""
    return capability in ROLE_CAPABILITIES.get(role, set())
