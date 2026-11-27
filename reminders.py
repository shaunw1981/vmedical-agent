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

import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import config
import db
import ghl
import mailer

_CLINIC_NAME = "Valley Medical"

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


# --- Editable content (templates live in the dashboard, not GoHighLevel) -----
def default_template(type_key: str) -> dict:
    return {
        "lead_days": 3,
        "email_subject": "Your {service} appointment at Valley Medical",
        "email_body": (
            "Hi {first_name},\n\n"
            "This is a friendly reminder of your {service} appointment on {date} at {time}.\n\n"
            "Please remember to:\n"
            "• Bring a pair of shorts\n"
            "• Avoid lotions or creams on the treatment area that day\n\n"
            "If you need to change your appointment, please let us know at least 2 days "
            "ahead so we can offer the time to someone else.\n\n"
            "See you soon,\nValley Medical"),
        "sms_text": (
            "Hi {first_name}, a reminder from Valley Medical: your {service} appointment is "
            "{date} at {time}. Please check your email for how to prepare, and call us if you "
            "need to change it."),
        "review_days": 0,
        "review_body": (
            "Hi {first_name}, we hope your recent {service} at Valley Medical went well! "
            "If you're happy with how things went, would you mind leaving us a quick review? "
            "It really helps us. Thank you!"),
    }


def template_for(type_key: str) -> dict:
    """The saved template merged over the default, so every type has full content."""
    d = default_template(type_key)
    t = db.get_reminder_template(type_key)
    if t:
        for k in ("lead_days", "email_subject", "email_body", "sms_text", "review_days", "review_body"):
            if t.get(k) not in (None, ""):
                d[k] = t[k]
    return d


def _subst(text: str, name: str, local_dt: datetime, label: str) -> str:
    first = (name or "").strip().split(" ")[0] or "there"
    return ((text or "")
            .replace("{first_name}", first)
            .replace("{name}", (name or "").strip())
            .replace("{service}", label)
            .replace("{date}", local_dt.strftime("%A, %B %-d"))
            .replace("{time}", local_dt.strftime("%-I:%M %p"))
            .replace("{clinic}", _CLINIC_NAME))


def render_content(type_key: str, name: str, local_dt: datetime) -> dict:
    """Ready-to-edit content for one appointment, from its type template."""
    label = config.APPOINTMENT_TYPE_LABELS.get(type_key, "appointment")
    t = template_for(type_key)
    return {
        "lead_days": int(t["lead_days"]),
        "email_subject": _subst(t["email_subject"], name, local_dt, label),
        "email_body": _subst(t["email_body"], name, local_dt, label),
        "sms_text": _subst(t["sms_text"], name, local_dt, label),
        "review_days": int(t["review_days"]),
        "review_body": _subst(t["review_body"], name, local_dt, label),
    }


# --- Scheduling --------------------------------------------------------------
def schedule(name: str, appt_at: str, type_key: str,
             email: Optional[str] = None, phone: Optional[str] = None,
             created_by: Optional[str] = None, patient_id: Optional[int] = None,
             email_subject: Optional[str] = None, email_body: Optional[str] = None,
             sms_text: Optional[str] = None, lead_days=None, review_days=None,
             review_body: Optional[str] = None) -> dict:
    """
    Log an appointment and queue its reminders. The dashboard owns the content and
    the timing; the background sender delivers email (and SMS via GHL) when due.
    Returns {"ok": bool, "appointment_id"|"error", ...}; never raises.
    """
    name = (name or "").strip()
    email = (email or "").strip() or None
    phone = (phone or "").strip() or None
    if not name:
        return {"ok": False, "error": "A patient name is required."}
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

    base = render_content(type_key, name, local_dt)
    email_subject = (email_subject or "").strip() or base["email_subject"]
    email_body = (email_body if email_body not in (None, "") else base["email_body"])
    sms_text = (sms_text if sms_text not in (None, "") else base["sms_text"])
    ld = int(lead_days) if str(lead_days).strip() not in ("", "None") else base["lead_days"]
    rd = int(review_days) if str(review_days).strip() not in ("", "None") else base["review_days"]
    review_body = (review_body if review_body not in (None, "") else base["review_body"])

    reminder_due = (local_dt - timedelta(days=ld)).strftime("%Y-%m-%dT%H:%M")
    review_due = (local_dt + timedelta(days=rd)).strftime("%Y-%m-%dT%H:%M") if rd > 0 else None

    # Sync a GHL contact so we can text them (best effort — email still works without it).
    ghl_contact_id, ghl_appt_id, warning = None, None, None
    if phone and config.ghl_contacts_enabled():
        try:
            c = ghl.upsert_contact(config.reminder_location_id(), name, email=email, phone=phone,
                                   tags=[f"Appointment: {label}"])
            ghl_contact_id = c.get("id")
        except Exception as exc:  # noqa: BLE001
            warning = f"Saved, but couldn't sync to GoHighLevel for texting: {exc}"
        cal = get_calendar_map().get(type_key, {})
        if ghl_contact_id and cal.get("id"):
            try:
                s, e = to_ghl_times(local_dt)
                appt = ghl.create_appointment(config.reminder_location_id(), cal["id"],
                                              ghl_contact_id, s, e, title=f"{label} — {name}")
                ghl_appt_id = appt.get("id") or None
            except Exception:  # noqa: BLE001
                pass

    appt_id = db.add_appointment(
        contact_name=name, appt_at=appt_iso, type_key=type_key, type_label=label,
        email=email, phone=phone, ghl_contact_id=ghl_contact_id, ghl_appointment_id=ghl_appt_id,
        created_by=created_by, patient_id=patient_id, lead_days=ld, email_subject=email_subject,
        email_body=email_body, sms_text=sms_text, reminder_due_at=reminder_due,
        review_days=rd, review_body=review_body, review_due_at=review_due,
    )
    res = {"ok": True, "appointment_id": appt_id, "label": label,
           "reminder_due_at": reminder_due,
           "channels": {"email": bool(email and email_body),
                        "sms": bool(ghl_contact_id and sms_text)}}
    if warning:
        res["warning"] = warning
    return res


# --- Delivery (runs in the background on a timer) ----------------------------
def send_due() -> dict:
    """Send any reminders/review asks that are due. Safe to call repeatedly."""
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    sent_rem = sent_rev = 0
    errors: list[str] = []
    for a in db.due_reminders(now):
        attempted = ok = False
        if a.get("email") and (a.get("email_body") or "").strip() and mailer.enabled():
            attempted = True
            try:
                mailer.send_email(a["email"], a.get("email_subject") or "Your appointment reminder",
                                  a["email_body"], from_addr=config.CLINIC_REPLY_FROM,
                                  reply_to=config.CLINIC_REPLY_FROM)
                ok = True
            except Exception as exc:  # noqa: BLE001
                errors.append(f"appt {a['id']} email: {exc}")
        if a.get("ghl_contact_id") and (a.get("sms_text") or "").strip() and config.ghl_contacts_enabled():
            attempted = True
            try:
                ghl.send_sms(a["ghl_contact_id"], a["sms_text"])
                ok = True
            except Exception as exc:  # noqa: BLE001
                errors.append(f"appt {a['id']} sms: {exc}")
        if ok or not attempted:        # mark done on success, or when there's nothing to send
            db.mark_reminder_sent(a["id"])
            sent_rem += 1
    for a in db.due_reviews(now):
        if a.get("email") and (a.get("review_body") or "").strip() and mailer.enabled():
            try:
                mailer.send_email(a["email"], "How was your visit to Valley Medical?",
                                  a["review_body"], from_addr=config.CLINIC_REPLY_FROM,
                                  reply_to=config.CLINIC_REPLY_FROM)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"appt {a['id']} review: {exc}")
        db.mark_review_sent(a["id"])
        sent_rev += 1
    return {"reminders": sent_rem, "reviews": sent_rev, "errors": errors}


_scheduler_started = False


def start_scheduler(interval: int = 300) -> None:
    """Start a daemon thread that delivers due reminders every `interval` seconds."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    def _loop():
        while True:
            try:
                send_due()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(interval)

    threading.Thread(target=_loop, name="reminder-scheduler", daemon=True).start()
