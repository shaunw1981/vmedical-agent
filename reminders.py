"""
reminders.py — appointment-reminder scheduling logic.

The team fills a small form (contact + date/time + appointment type). We:
  1. create/update the contact in GoHighLevel,
  2. drop them into the GHL workflow mapped to that appointment type (passing the
     appointment time so the workflow's reminder timing works),
  3. record it locally so it stays listed on the dashboard.

The type -> workflow mapping is configured in-app (Reminder settings) and stored
in the settings table, so workflow ids never live in code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import config
import db
import ghl

_MAP_PREFIX = "appt_workflow:"       # -> workflow id
_MAP_NAME_PREFIX = "appt_workflow_name:"  # -> workflow name (for display)


# --- Timezone ----------------------------------------------------------------
def _clinic_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(config.CLINIC_TIMEZONE)
    except Exception:  # noqa: BLE001 - missing tzdata etc.; fall back to naive
        return None


def parse_appt_at(value: str) -> datetime:
    """Parse an <input type=datetime-local> value ('2026-08-10T14:30')."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Please choose an appointment date and time.")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("That date/time wasn't understood — please re-enter it.")


def to_ghl_event_time(local_dt: datetime) -> str:
    """A naive local appointment time -> ISO8601 with the clinic's UTC offset."""
    tz = _clinic_tz()
    if tz is not None and local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=tz)
    return local_dt.isoformat()


def format_appt(appt_at: str) -> str:
    """Human display for a stored 'YYYY-MM-DDTHH:MM' value."""
    try:
        return datetime.fromisoformat(appt_at).strftime("%a, %b %-d, %Y · %-I:%M %p")
    except (ValueError, TypeError):
        return appt_at


# --- Workflow mapping (type_key -> GHL workflow) -----------------------------
def get_workflow_map() -> dict[str, dict]:
    """{type_key: {'id': workflow_id, 'name': workflow_name}} for every type."""
    out: dict[str, dict] = {}
    for key, _label in config.APPOINTMENT_TYPES:
        wid = db.get_setting(_MAP_PREFIX + key)
        out[key] = {"id": wid or "", "name": db.get_setting(_MAP_NAME_PREFIX + key) or ""}
    return out


def set_workflow_map(type_key: str, workflow_id: str, workflow_name: str = "") -> None:
    workflow_id = (workflow_id or "").strip()
    if workflow_id:
        db.set_setting(_MAP_PREFIX + type_key, workflow_id)
        db.set_setting(_MAP_NAME_PREFIX + type_key, (workflow_name or "").strip())
    else:
        db.delete_setting(_MAP_PREFIX + type_key)
        db.delete_setting(_MAP_NAME_PREFIX + type_key)


def mapping_complete() -> bool:
    m = get_workflow_map()
    return all(m[k]["id"] for k, _ in config.APPOINTMENT_TYPES)


# --- Scheduling --------------------------------------------------------------
def schedule(name: str, appt_at: str, type_key: str,
             email: Optional[str] = None, phone: Optional[str] = None,
             created_by: Optional[str] = None) -> dict:
    """
    Do the whole flow. Returns {"ok": bool, "appointment_id"|"error", ...}.
    Raises nothing — callers show result["error"] on failure.
    """
    name = (name or "").strip()
    email = (email or "").strip() or None
    phone = (phone or "").strip() or None
    if not name:
        return {"ok": False, "error": "A contact name is required."}
    if not email and not phone:
        return {"ok": False, "error": "Enter an email or a phone number so we can reach them."}

    label = config.APPOINTMENT_TYPE_LABELS.get(type_key)
    if not label:
        return {"ok": False, "error": "Choose an appointment type."}

    try:
        local_dt = parse_appt_at(appt_at)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    appt_iso = local_dt.strftime("%Y-%m-%dT%H:%M")

    if not config.ghl_contacts_enabled():
        return {"ok": False, "error": "GoHighLevel isn't connected yet (set GHL_API_TOKEN "
                                       "and a reminder location)."}

    wf = get_workflow_map().get(type_key, {})
    workflow_id = wf.get("id")
    if not workflow_id:
        return {"ok": False, "error": f"No GoHighLevel workflow is mapped to "
                                      f"“{label}” yet — set it in Reminder settings."}

    location_id = config.reminder_location_id()
    try:
        contact = ghl.upsert_contact(location_id, name, email=email, phone=phone,
                                     tags=[f"Appointment: {label}"])
        contact_id = contact["id"]
        ghl.add_contact_to_workflow(contact_id, workflow_id,
                                    event_start_time=to_ghl_event_time(local_dt))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"GoHighLevel error: {exc}"}

    appt_id = db.add_appointment(
        contact_name=name, appt_at=appt_iso, type_key=type_key, type_label=label,
        email=email, phone=phone, workflow_id=workflow_id,
        workflow_name=wf.get("name") or "", ghl_contact_id=contact_id, created_by=created_by,
    )
    return {"ok": True, "appointment_id": appt_id, "contact_id": contact_id, "label": label}
