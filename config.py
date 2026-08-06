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

# Only allow logins from this Google Workspace domain (e.g. "glowmedspa.com").
# Leave blank to allow any Google account (not recommended for production).
ALLOWED_EMAIL_DOMAIN = os.environ.get("ALLOWED_EMAIL_DOMAIN", "").strip().lower()

# The email that should automatically be the Super Admin on first login.
SUPER_ADMIN_EMAIL = os.environ.get("SUPER_ADMIN_EMAIL", "").strip().lower()

# Google OAuth credentials (from Google Cloud Console).
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

# Optional shared secret so only GoHighLevel can post to the call webhook.
GHL_WEBHOOK_SECRET = os.environ.get("GHL_WEBHOOK_SECRET", "").strip()

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
ROLE_CAPABILITIES = {
    "super_admin": {
        "view_messages",
        "respond_messages",
        "manage_users",
        "manage_settings",
    },
    "spa_manager": {
        "view_messages",
        "respond_messages",
        "manage_users",  # managers can manage team members (but not super admins)
    },
    "team_member": {
        "view_messages",
        "respond_messages",
    },
}


def can(role: str, capability: str) -> bool:
    """True if the given role is allowed to do the given thing."""
    return capability in ROLE_CAPABILITIES.get(role, set())
