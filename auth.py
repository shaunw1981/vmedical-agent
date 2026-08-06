"""
auth.py — "Sign in with Google" and the role logic.

Flow:
  1. User clicks "Sign in with Google" -> we send them to Google.
  2. Google sends them back to /auth/callback with proof of who they are.
  3. We check their email is on the allowed company domain, create their account
     on first login (as Super Admin if they're the configured owner, otherwise
     as a Team Member), and remember them in a signed session cookie.

New team members simply sign in with Google once; a Super Admin or Spa Manager
then sets their role from the Team page.
"""

from typing import Optional

from authlib.integrations.starlette_client import OAuth
from fastapi import Request

import config
import db

oauth = OAuth()

# Only register Google if credentials are present, so the app still boots for
# local testing without them.
if config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def google_configured() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


class LoginError(Exception):
    """Raised when a login should be refused (wrong domain, etc.)."""


def role_for_new_user(email: str) -> str:
    """First-time users become Super Admin if they're the owner, else Team Member."""
    if config.SUPER_ADMIN_EMAIL and email.lower() == config.SUPER_ADMIN_EMAIL:
        return "super_admin"
    return config.DEFAULT_ROLE


def process_google_userinfo(userinfo: dict) -> dict:
    """
    Validate a Google profile and return the local user record.
    Raises LoginError if the login should be refused.
    """
    email = (userinfo.get("email") or "").lower()
    name = userinfo.get("name") or email
    if not email:
        raise LoginError("Google did not return an email address.")

    # Decide whether this account is allowed to sign in. Allowed when:
    #   - no restriction is configured (allow anyone), OR
    #   - the email's domain is in the allowed list, OR
    #   - it's the owner (Super Admin) email, OR
    #   - it's explicitly listed as an extra allowed email.
    domain = email.split("@")[-1]
    allowed = (
        not config.ALLOWED_EMAIL_DOMAINS
        or domain in config.ALLOWED_EMAIL_DOMAINS
        or email == config.SUPER_ADMIN_EMAIL
        or email in config.EXTRA_ALLOWED_EMAILS
    )
    if not allowed:
        raise LoginError("This account isn't approved to sign in. Contact your administrator.")

    user = db.upsert_user_on_login(email, name, role_for_new_user(email))
    if not user["active"]:
        raise LoginError("This account has been disabled. Contact an administrator.")
    return user


def current_user(request: Request) -> Optional[dict]:
    """
    The logged-in user for this request, or None. We re-read the role from the
    database every request so role changes take effect immediately.
    """
    session_user = request.session.get("user")
    if not session_user:
        return None
    user = db.get_user_by_email(session_user["email"])
    if not user or not user["active"]:
        return None
    return user
