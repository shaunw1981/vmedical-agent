"""
health.py — system health checks for the public /health probe and the in-app
/status page.

/health is hit frequently by an external uptime monitor, so basic_health() is
deliberately light (database + disk only) and never makes outbound calls. The
/status page calls full_status(), which may do slower, outbound checks
(WordPress, GoHighLevel, Ollama) since it's loaded on demand by a person.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import auth
import config
import db
import obsidian

# Disk thresholds (GB of free space).
_DISK_CRITICAL_GB = 0.5
_DISK_WARN_GB = 3.0


def _uses_ollama() -> bool:
    vals = {config.CHARLIE_PROVIDER, config.CHARLIE_CONVERSE_PROVIDER,
            config.CHARLIE_CONTENT_PROVIDER}
    return "ollama" in {v for v in vals if v}


# --- Individual checks -------------------------------------------------------
def check_database() -> dict:
    try:
        db.get_setting("__healthcheck__")   # a trivial SELECT
        return {"name": "Database", "level": "ok", "detail": "Local database is readable."}
    except Exception as exc:  # noqa: BLE001
        return {"name": "Database", "level": "down", "detail": f"Database error: {exc}"}


def check_disk() -> dict:
    try:
        target = Path(config.photos_path())
        # Walk up to the nearest directory that exists (the volume is the same).
        while not target.exists() and target != target.parent:
            target = target.parent
        usage = shutil.disk_usage(str(target))
        free_gb = usage.free / (1024 ** 3)
        detail = f"{free_gb:.1f} GB free of {usage.total / (1024 ** 3):.0f} GB."
        if free_gb < _DISK_CRITICAL_GB:
            return {"name": "Disk space", "level": "down", "detail": f"Critically low — {detail}"}
        if free_gb < _DISK_WARN_GB:
            return {"name": "Disk space", "level": "warn", "detail": f"Running low — {detail}"}
        return {"name": "Disk space", "level": "ok", "detail": detail, "free_gb": round(free_gb, 1)}
    except Exception as exc:  # noqa: BLE001
        return {"name": "Disk space", "level": "warn", "detail": f"Couldn't read disk usage: {exc}"}


def check_ollama() -> dict:
    if not _uses_ollama():
        return {"name": "Local AI (Ollama)", "level": "off", "detail": "Not in use (using the Anthropic API)."}
    try:
        import charlie
        st = charlie.ollama_status()
        if not st.get("reachable"):
            return {"name": "Local AI (Ollama)", "level": "warn",
                    "detail": f"Not reachable at {st.get('url')} — {st.get('error', 'no response')}."}
        if st.get("model_available") is False:
            return {"name": "Local AI (Ollama)", "level": "warn",
                    "detail": f"Running, but model {st.get('model')} isn't pulled."}
        return {"name": "Local AI (Ollama)", "level": "ok", "detail": f"Reachable; model {st.get('model')} ready."}
    except Exception as exc:  # noqa: BLE001
        return {"name": "Local AI (Ollama)", "level": "warn", "detail": f"Check failed: {exc}"}


def check_obsidian() -> dict:
    try:
        import obsidian
        if obsidian.is_configured():
            return {"name": "Knowledge vault (Obsidian)", "level": "ok", "detail": "Vault connected."}
        return {"name": "Knowledge vault (Obsidian)", "level": "warn",
                "detail": "Not connected — notes save to the database only."}
    except Exception as exc:  # noqa: BLE001
        return {"name": "Knowledge vault (Obsidian)", "level": "warn", "detail": str(exc)}


def check_wordpress() -> dict:
    if not config.wordpress_enabled():
        return {"name": "WordPress (blog)", "level": "off", "detail": "Not configured."}
    try:
        import wordpress
        res = wordpress.test_connection()
        if res.get("ok"):
            return {"name": "WordPress (blog)", "level": "ok", "detail": "Connected."}
        return {"name": "WordPress (blog)", "level": "warn", "detail": res.get("error", "Connection problem.")}
    except Exception as exc:  # noqa: BLE001
        return {"name": "WordPress (blog)", "level": "warn", "detail": str(exc)}


def check_ghl() -> dict:
    if not config.ghl_contacts_enabled():
        return {"name": "GoHighLevel", "level": "off", "detail": "Not configured."}
    try:
        import ghl
        ghl.search_contacts(config.reminder_location_id(), "a", limit=1)
        return {"name": "GoHighLevel", "level": "ok", "detail": "API reachable."}
    except Exception as exc:  # noqa: BLE001
        return {"name": "GoHighLevel", "level": "warn", "detail": f"Not reachable: {exc}"}


def check_email() -> dict:
    if config.email_send_enabled():
        return {"name": "Email sending", "level": "ok", "detail": "Configured."}
    return {"name": "Email sending", "level": "off", "detail": "Not configured."}


# --- Aggregates --------------------------------------------------------------
def basic_health() -> tuple[dict, bool]:
    """Light check for the public /health probe. Returns (payload, ok)."""
    checks = [check_database(), check_disk()]
    critical = any(c["level"] == "down" for c in checks)
    payload = {
        "status": "down" if critical else "ok",
        "google_login": auth.google_configured(),
        "obsidian": obsidian.is_configured(),
        "checks": {c["name"]: c["level"] for c in checks},
    }
    warnings = [c["detail"] for c in checks if c["level"] == "warn"]
    if warnings:
        payload["warnings"] = warnings
    return payload, not critical


def full_status() -> dict:
    """Rich check for the /status page (may make outbound calls)."""
    checks = [
        {"name": "Dashboard app", "level": "ok", "detail": "Serving requests."},
        check_database(),
        check_disk(),
        check_ollama(),
        check_obsidian(),
        check_email(),
        check_wordpress(),
        check_ghl(),
    ]
    down = sum(1 for c in checks if c["level"] == "down")
    warn = sum(1 for c in checks if c["level"] == "warn")
    overall = "down" if down else ("degraded" if warn else "ok")
    return {"overall": overall, "checks": checks, "down": down, "warn": warn}
