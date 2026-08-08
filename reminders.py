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

from datetime import datetime, timedelta
from typing import Optional

import config
import db
import ghl

_MAP_PREFIX = "appt_workflow:"       # -> workflow id
_MAP_NAME_PREFIX = "appt_workflow_name:"  # -> workflow name (for display)
_CAL_PREFIX = "appt_calendar:"       # -> calendar id
_CAL_NAME_PREFIX = "appt_calendar_name:"  # -> calendar name (for display)


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


def _localize(local_dt: datetime) -> datetime:
    tz = _clinic_tz()
    if tz is not None and local_dt.tzinfo is None:
        return local_dt.replace(tzinfo=tz)
    return local_dt


def localize(local_dt: datetime) -> datetime:
    """Public: attach the clinic timezone to a naive datetime."""
    return _localize(local_dt)


def to_ghl_event_time(local_dt: datetime) -> str:
    """A naive local appointment time -> ISO8601 with the clinic's UTC offset."""
    return _localize(local_dt).isoformat()


def to_ghl_times(local_dt: datetime) -> tuple[str, str]:
    """(start, end) ISO8601 strings, end = start + configured appointment length."""
    start = _localize(local_dt)
    end = start + timedelta(minutes=config.APPOINTMENT_DURATION_MINUTES)
    return start.isoformat(), end.isoformat()


def format_appt(appt_at: str) -> str:
    """Human display for a stored 'YYYY-MM-DDTHH:MM' value."""
    try:
        return datetime.fromisoformat(appt_at).strftime("%a, %b %-d, %Y · %-I:%M %p")
    except (ValueError, TypeError):
        return appt_at


def format_iso(value: str) -> str:
    """Friendly display for any ISO8601 timestamp (with Z or offset)."""
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime(
            "%b %-d, %Y · %-I:%M %p")
    except (ValueError, TypeError):
        return str(value)[:16].replace("T", " ")


# --- Workflow mapping (type_key -> GHL workflow) -----------------------------
def get_workflow_map() -> dict[str, dict]:
    """{type_key: {'id': workflow_id, 'name': workflow_name}} for every type.

    Falls back to config.DEFAULT_APPOINTMENT_WORKFLOWS when no in-app override
    is set, so reminders work out of the box.
    """
    out: dict[str, dict] = {}
    for key, _label in config.APPOINTMENT_TYPES:
        wid = db.get_setting(_MAP_PREFIX + key) or config.DEFAULT_APPOINTMENT_WORKFLOWS.get(key, "")
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


def get_calendar_map() -> dict[str, dict]:
    """{type_key: {'id': calendar_id, 'name': calendar_name}}; empty id = don't book."""
    out: dict[str, dict] = {}
    for key, _label in config.APPOINTMENT_TYPES:
        out[key] = {"id": db.get_setting(_CAL_PREFIX + key) or "",
                    "name": db.get_setting(_CAL_NAME_PREFIX + key) or ""}
    return out


def set_calendar_map(type_key: str, calendar_id: str, calendar_name: str = "") -> None:
    calendar_id = (calendar_id or "").strip()
    if calendar_id:
        db.set_setting(_CAL_PREFIX + type_key, calendar_id)
        db.set_setting(_CAL_NAME_PREFIX + type_key, (calendar_name or "").strip())
    else:
        db.delete_setting(_CAL_PREFIX + type_key)
        db.delete_setting(_CAL_NAME_PREFIX + type_key)


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

    # Also book a real appointment on the contact's record, if a calendar is set
    # for this type. A booking failure must not lose the (already-added) reminder.
    cal = get_calendar_map().get(type_key, {})
    ghl_appt_id, warning = None, None
    if cal.get("id"):
        try:
            start_iso, end_iso = to_ghl_times(local_dt)
            appt = ghl.create_appointment(location_id, cal["id"], contact_id,
                                          start_iso, end_iso, title=f"{label} — {name}")
            ghl_appt_id = appt.get("id") or None
        except Exception as exc:  # noqa: BLE001
            warning = f"Contact added to the workflow, but the GHL appointment couldn't be booked: {exc}"

    appt_id = db.add_appointment(
        contact_name=name, appt_at=appt_iso, type_key=type_key, type_label=label,
        email=email, phone=phone, workflow_id=workflow_id,
        workflow_name=wf.get("name") or "", ghl_contact_id=contact_id,
        ghl_appointment_id=ghl_appt_id, created_by=created_by,
    )
    result = {"ok": True, "appointment_id": appt_id, "contact_id": contact_id,
              "label": label, "booked": bool(ghl_appt_id)}
    if warning:
        result["warning"] = warning
    return result
