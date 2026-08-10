"""
vmedical-agent — the team dashboard (Build #1).

Runs on the Mac Mini. The team signs in with Google, and (based on their role:
Super Admin / Spa Manager / Team Member) sees the after-hours phone-message
inbox. GoHighLevel's AI receptionist posts call transcripts to /webhook/ghl/call;
each one is filed into the Obsidian vault under the caller's number and shown in
the inbox for the team to mark "responded."

See SETUP-MACMINI.md for how to run it and connect Google + GoHighLevel.
"""

import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import auth
import charlie
import charts
import config
import db
import email_monitor
import ghl
import granola
import inbox as inbox_svc
import mailer
import meetings as meetings_svc
import obsidian
import reminders

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="vmedical-agent dashboard", version="4.6.0")
# Allow the Chrome extension (chrome-extension://<id>) to call the JSON API.
# Only extension origins get CORS; browser session routes are unaffected.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"chrome-extension://.*",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _fmt_num(n) -> str:
    """Format a number with thousands separators for display (e.g. 12,340)."""
    try:
        f = float(n)
        return f"{int(f):,}" if f == int(f) else f"{f:,.1f}"
    except (TypeError, ValueError):
        return str(n)


# Make role/permission helpers available inside every template.
templates.env.globals.update(
    can=config.can, ROLE_LABELS=config.ROLE_LABELS, ROLES=config.ROLES, fmt=_fmt_num,
    ASSET_VER=app.version,  # cache-buster for /static/app.css & app.js
)


# --- Static / PWA files ------------------------------------------------------
@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Served from root so its scope can control the whole app.
    return FileResponse(STATIC_DIR / "js" / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "icons" / "favicon.png", media_type="image/png")


@app.get("/offline", response_class=HTMLResponse, include_in_schema=False)
def offline(request: Request):
    # Neutral, auth-free page the service worker falls back to when offline.
    return templates.TemplateResponse("offline.html", {"request": request})


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    email_monitor.start_background()


def _ctx(request: Request, user: dict, **extra) -> dict:
    """Shared template context (adds nav data like the unread count)."""
    base = {
        "request": request,
        "user": user,
        "new_count": db.count_new_messages(),
        "meetings_pending": db.count_pending_meetings(),
        "inbox_count": db.count_inbox_attention(),
        "obsidian_ok": obsidian.is_configured(),
    }
    base.update(extra)
    return base


def _guard(request: Request, capability=None):
    """
    Returns (user, response). If response is not None, the route should return it
    (a redirect to login, or a 403 page). Otherwise user is the logged-in person.
    """
    user = auth.current_user(request)
    if not user:
        return None, RedirectResponse("/login", status_code=303)
    if capability and not config.can(user["role"], capability):
        return user, templates.TemplateResponse(
            "403.html", _ctx(request, user), status_code=403
        )
    return user, None


# --- Health ------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "google_login": auth.google_configured(),
        "obsidian": obsidian.is_configured(),
    }


# --- Auth --------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if auth.current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "google_ok": auth.google_configured()},
    )


@app.get("/auth/google")
async def auth_google(request: Request):
    if not auth.google_configured():
        return RedirectResponse("/login", status_code=303)
    redirect_uri = f"{config.BASE_URL}/auth/callback"
    return await auth.oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        token = await auth.oauth.google.authorize_access_token(request)
        userinfo = token.get("userinfo") or await auth.oauth.google.userinfo(token=token)
        user = auth.process_google_userinfo(dict(userinfo))
    except auth.LoginError as exc:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "google_ok": True, "error": str(exc)},
            status_code=403,
        )
    except Exception:  # noqa: BLE001
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "google_ok": True,
             "error": "Sign-in failed. Please try again."},
            status_code=400,
        )

    request.session["user"] = {"email": user["email"]}
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# --- Dashboard ---------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user, resp = _guard(request)
    if resp:
        return resp

    daily = db.messages_by_day(14)
    week_total = sum(d["total"] for d in daily[-7:])
    prev_week = sum(d["total"] for d in daily[-14:-7])
    status = db.status_breakdown()
    rate = round(status["responded"] / status["total"] * 100) if status["total"] else 0

    daily_bars = charts.bar_series([d["total"] for d in daily], [d["label"] for d in daily])
    status_donut = charts.donut_segments([
        ("Responded", status["responded"], "#7c8a73"),
        ("New", status["new"], "#d8ded2"),
    ])

    return templates.TemplateResponse(
        "dashboard.html",
        _ctx(
            request, user,
            responded_count=status["responded"],
            week_total=week_total,
            rate_str=f"{rate}%",
            msg_trend={"change": week_total - prev_week},
            daily_bars=daily_bars,
            status_donut=status_donut,
            recent=db.list_messages()[:5],
            today=datetime.now().strftime("%A, %B %-d, %Y"),
            upcoming_appts=db.list_upcoming_appointments(5),
            upcoming_appts_count=db.count_upcoming_appointments(),
            fmt_appt=reminders.format_appt,
        ),
    )


# --- Social media metrics ----------------------------------------------------
def _resolve_social_range(range_key: str, start: str, end: str):
    """Turn the ?range/&start/&end query into (key, start_str, end_str, start_dt, end_dt, label)."""
    today = date.today()
    key = range_key if range_key in ("7", "30", "90", "custom") else "7"
    sd = ed = None
    if key == "custom":
        try:
            sd, ed = date.fromisoformat(start), date.fromisoformat(end)
            if ed < sd:
                sd, ed = ed, sd
        except (ValueError, TypeError):
            key = "7"
    if key != "custom":
        days = int(key)
        ed = today
        sd = today - timedelta(days=days - 1)
    start_dt = reminders.localize(datetime(sd.year, sd.month, sd.day, 0, 0, 0))
    end_dt = reminders.localize(datetime(ed.year, ed.month, ed.day, 23, 59, 59))
    if key == "custom":
        label = f"{sd.strftime('%b %-d, %Y')} – {ed.strftime('%b %-d, %Y')}"
    else:
        label = f"Last {key} days vs previous {key}"
    return key, sd.isoformat(), ed.isoformat(), start_dt, end_dt, label


@app.get("/social", response_class=HTMLResponse)
def social(request: Request, debug: int = 0, range: str = "7", start: str = "", end: str = ""):
    user, resp = _guard(request, "view_social")
    if resp:
        return resp
    range_key, r_start, r_end, start_dt, end_dt, label = _resolve_social_range(range, start, end)

    # Diagnostic dump (super admin only) — confirm GHL's response shapes and
    # whether the statistics endpoint honored the date range.
    if debug and config.can(user["role"], "manage_settings"):
        import json
        from fastapi.responses import PlainTextResponse
        if not config.ghl_social_enabled():
            return PlainTextResponse("GHL not configured (set GHL_API_TOKEN and GHL_LOCATIONS).")
        try:
            return PlainTextResponse(json.dumps(ghl.raw_debug(start=start_dt, end=end_dt), indent=2, default=str))
        except Exception as exc:  # noqa: BLE001
            return PlainTextResponse(f"ERROR: {exc}", status_code=500)

    data = None
    error = None
    if config.ghl_social_enabled():
        try:
            data = ghl.social_overview(start=start_dt, end=end_dt, window_label=label)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return templates.TemplateResponse(
        "social.html",
        _ctx(
            request,
            user,
            social=data,
            social_error=error,
            social_enabled=config.ghl_social_enabled(),
            range_key=range_key,
            range_start=r_start,
            range_end=r_end,
        ),
    )


# --- Appointment reminders ---------------------------------------------------
def _reminders_ctx(request: Request, user: dict, **extra) -> dict:
    return _ctx(
        request, user,
        appt_types=config.APPOINTMENT_TYPES,
        reminders_enabled=config.ghl_contacts_enabled(),
        mapping_complete=reminders.mapping_complete(),
        fmt_appt=reminders.format_appt,
        clinic_tz=config.CLINIC_TIMEZONE,
        flash=request.session.pop("reminder_flash", None),
        **extra,
    )


@app.get("/reminders", response_class=HTMLResponse)
def reminders_page(request: Request):
    user, resp = _guard(request, "view_reminders")
    if resp:
        return resp
    return templates.TemplateResponse(
        "reminders.html",
        _reminders_ctx(request, user, appointments=db.list_appointments()),
    )


@app.post("/reminders")
def reminders_create(
    request: Request,
    contact_name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    appt_at: str = Form(...),
    type_key: str = Form(...),
):
    user, resp = _guard(request, "schedule_reminders")
    if resp:
        return resp
    result = reminders.schedule(
        name=contact_name, appt_at=appt_at, type_key=type_key,
        email=email, phone=phone, created_by=user["email"],
    )
    if result["ok"]:
        msg = (f"Reminder scheduled for {contact_name} — added to the "
               f"“{result['label']}” follow-up in GoHighLevel")
        msg += " and booked on the calendar." if result.get("booked") else "."
        if result.get("warning"):
            msg += f" ⚠️ {result['warning']}"
        request.session["reminder_flash"] = {"ok": True, "msg": msg}
    else:
        request.session["reminder_flash"] = {"ok": False, "msg": result["error"]}
    return RedirectResponse("/reminders", status_code=303)


@app.post("/reminders/{appt_id}/cancel")
def reminders_cancel(request: Request, appt_id: int):
    user, resp = _guard(request, "schedule_reminders")
    if resp:
        return resp
    db.cancel_appointment(appt_id)
    request.session["reminder_flash"] = {"ok": True, "msg": "Reminder marked cancelled "
                                         "(this doesn't remove them from GoHighLevel)."}
    return RedirectResponse("/reminders", status_code=303)


@app.get("/reminders/settings", response_class=HTMLResponse)
def reminders_settings(request: Request, debug: int = 0):
    user, resp = _guard(request, "manage_settings")
    if resp:
        return resp
    # Diagnostic dump — confirm GHL's contact/workflow response shapes on connect.
    if debug:
        import json
        from fastapi.responses import PlainTextResponse
        if not config.ghl_contacts_enabled():
            return PlainTextResponse("GHL not configured (set GHL_API_TOKEN and a reminder location).")
        try:
            return PlainTextResponse(
                json.dumps(ghl.reminders_debug(config.reminder_location_id()), indent=2, default=str))
        except Exception as exc:  # noqa: BLE001
            return PlainTextResponse(f"ERROR: {exc}", status_code=500)
    workflows, calendars, wf_error = [], [], None
    if config.ghl_contacts_enabled():
        loc = config.reminder_location_id()
        try:
            workflows = ghl.list_workflows(loc)
        except Exception as exc:  # noqa: BLE001
            wf_error = str(exc)
        try:
            calendars = ghl.list_calendars(loc)
        except Exception:  # noqa: BLE001 - calendars are optional; ignore load errors
            calendars = []
    return templates.TemplateResponse(
        "reminders_settings.html",
        _reminders_ctx(request, user, workflows=workflows, calendars=calendars,
                       wf_error=wf_error, mapping=reminders.get_workflow_map(),
                       cal_mapping=reminders.get_calendar_map()),
    )


@app.post("/reminders/settings")
async def reminders_settings_save(request: Request):
    user, resp = _guard(request, "manage_settings")
    if resp:
        return resp
    form = await request.form()
    # Build name lookups so we can store each workflow/calendar's display name too.
    wf_names: dict[str, str] = {}
    cal_names: dict[str, str] = {}
    if config.ghl_contacts_enabled():
        loc = config.reminder_location_id()
        try:
            wf_names = {w["id"]: w["name"] for w in ghl.list_workflows(loc)}
        except Exception:  # noqa: BLE001
            wf_names = {}
        try:
            cal_names = {c["id"]: c["name"] for c in ghl.list_calendars(loc)}
        except Exception:  # noqa: BLE001
            cal_names = {}
    for key, _label in config.APPOINTMENT_TYPES:
        wid = (form.get(f"wf_{key}") or "").strip()
        reminders.set_workflow_map(key, wid, wf_names.get(wid, ""))
        cid = (form.get(f"cal_{key}") or "").strip()
        reminders.set_calendar_map(key, cid, cal_names.get(cid, ""))
    request.session["reminder_flash"] = {"ok": True, "msg": "Workflow &amp; calendar mapping saved."}
    return RedirectResponse("/reminders/settings", status_code=303)


# --- JSON API (browser session OR X-API-Key) — for the future Chrome extension
def _api_authorized(request: Request) -> Optional[str]:
    """Returns the actor's email if authorized, else None."""
    user = auth.current_user(request)
    if user:
        return user["email"]
    key = request.headers.get("x-api-key", "")
    if config.DASHBOARD_API_KEY and key == config.DASHBOARD_API_KEY:
        return "api-key"
    return None


@app.get("/api/contacts/search")
def api_contacts_search(request: Request, q: str = ""):
    actor = _api_authorized(request)
    if not actor:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not config.ghl_contacts_enabled():
        return JSONResponse({"error": "GoHighLevel not configured"}, status_code=503)
    if len((q or "").strip()) < 2:
        return {"contacts": []}
    try:
        return {"contacts": ghl.search_contacts(config.reminder_location_id(), q)}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.post("/api/reminders")
async def api_reminders_create(request: Request):
    actor = _api_authorized(request)
    if not actor:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "expected JSON"}, status_code=400)
    # Attribute to the signed-in staffer when the extension sends it; otherwise
    # fall back to the authorizing actor (session email, or "api-key").
    staff = (body.get("staff") or "").strip()
    result = reminders.schedule(
        name=body.get("contact_name") or body.get("name") or "",
        appt_at=body.get("appt_at") or "",
        type_key=body.get("type_key") or "",
        email=body.get("email") or "",
        phone=body.get("phone") or "",
        created_by=staff or actor,
    )
    return JSONResponse(result, status_code=200 if result["ok"] else 400)


@app.get("/api/appointment-types")
def api_appointment_types(request: Request):
    if not _api_authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"types": [{"key": k, "label": l} for k, l in config.APPOINTMENT_TYPES]}


# --- Client records ----------------------------------------------------------
@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request):
    user, resp = _guard(request, "view_clients")
    if resp:
        return resp
    return templates.TemplateResponse(
        "clients.html",
        _ctx(request, user,
             clients=db.list_client_summaries(),
             fmt_appt=reminders.format_appt,
             search_enabled=config.ghl_contacts_enabled(),
             flash=request.session.pop("clients_flash", None)),
    )


@app.post("/clients/new")
def client_create(
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    address1: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    postal_code: str = Form(""),
):
    user, resp = _guard(request, "view_clients")
    if resp:
        return resp
    name = f"{first_name.strip()} {last_name.strip()}".strip()
    if not name:
        request.session["clients_flash"] = {"ok": False, "msg": "Enter a first or last name."}
        return RedirectResponse("/clients", status_code=303)
    if not email.strip() and not phone.strip():
        request.session["clients_flash"] = {"ok": False, "msg": "Enter an email or phone number."}
        return RedirectResponse("/clients", status_code=303)
    if not config.ghl_contacts_enabled():
        request.session["clients_flash"] = {"ok": False, "msg": "GoHighLevel isn't connected yet."}
        return RedirectResponse("/clients", status_code=303)
    try:
        result = ghl.create_contact(config.reminder_location_id(), {
            "firstName": first_name, "lastName": last_name, "email": email, "phone": phone,
            "address1": address1, "city": city, "state": state, "postalCode": postal_code,
        })
        request.session["client_flash"] = {
            "ok": True,
            "msg": f"{name} added." if result.get("new") else f"{name} already existed — opened their record.",
        }
        return RedirectResponse(f"/clients/{result['id']}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        request.session["clients_flash"] = {"ok": False, "msg": f"Couldn't add contact: {exc}"}
        return RedirectResponse("/clients", status_code=303)


@app.get("/clients/{contact_id}", response_class=HTMLResponse)
def client_detail(request: Request, contact_id: str, debug: int = 0):
    user, resp = _guard(request, "view_clients")
    if resp:
        return resp
    if debug and config.can(user["role"], "manage_settings"):
        import json
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(json.dumps(ghl.clients_debug(contact_id), indent=2, default=str))

    contact, notes, ghl_appts, errors = None, [], [], {}
    if config.ghl_contacts_enabled():
        try:
            contact = ghl.get_contact(contact_id)
        except Exception as exc:  # noqa: BLE001
            errors["contact"] = str(exc)
        try:
            notes = ghl.list_contact_notes(contact_id)
        except Exception as exc:  # noqa: BLE001
            errors["notes"] = str(exc)
        try:
            ghl_appts = ghl.get_contact_appointments(contact_id)
        except Exception as exc:  # noqa: BLE001
            errors["appointments"] = str(exc)

    # Local records woven in: our scheduled reminders + after-hours calls.
    phone = (contact or {}).get("phone", "")
    email = (contact or {}).get("email", "")
    local_appts = db.list_appointments_for(ghl_contact_id=contact_id, email=email, phone=phone)
    calls = db.list_messages_for_phone(phone) if phone else []

    return templates.TemplateResponse(
        "client_detail.html",
        _ctx(request, user,
             contact_id=contact_id, contact=contact, notes=notes,
             ghl_appts=ghl_appts, local_appts=local_appts, calls=calls,
             errors=errors, fmt_appt=reminders.format_appt, fmt_dt=reminders.format_iso,
             ghl_enabled=config.ghl_contacts_enabled(),
             flash=request.session.pop("client_flash", None)),
    )


@app.post("/clients/{contact_id}/edit")
def client_edit(
    request: Request,
    contact_id: str,
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    address1: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    postal_code: str = Form(""),
):
    user, resp = _guard(request, "view_clients")
    if resp:
        return resp
    fields = {
        "firstName": first_name.strip(),
        "lastName": last_name.strip(),
        "email": email.strip(),
        "phone": phone.strip(),
        "address1": address1.strip(),
        "city": city.strip(),
        "state": state.strip(),
        "postalCode": postal_code.strip(),
    }
    try:
        ghl.update_contact(contact_id, fields)
        request.session["client_flash"] = {"ok": True, "msg": "Contact details updated."}
    except Exception as exc:  # noqa: BLE001
        request.session["client_flash"] = {"ok": False, "msg": f"Couldn't update contact: {exc}"}
    return RedirectResponse(f"/clients/{contact_id}", status_code=303)


@app.post("/clients/{contact_id}/note")
def client_add_note(request: Request, contact_id: str, body: str = Form(...)):
    user, resp = _guard(request, "view_clients")
    if resp:
        return resp
    text = (body or "").strip()
    if not text:
        request.session["client_flash"] = {"ok": False, "msg": "Note was empty — nothing added."}
    else:
        try:
            ghl.add_contact_note(contact_id, text)
            request.session["client_flash"] = {"ok": True, "msg": "Note added to GoHighLevel."}
        except Exception as exc:  # noqa: BLE001
            request.session["client_flash"] = {"ok": False, "msg": f"Couldn't add note: {exc}"}
    return RedirectResponse(f"/clients/{contact_id}", status_code=303)


# --- Inbox (Charlie's conversations) -----------------------------------------
@app.get("/inbox", response_class=HTMLResponse)
def inbox_page(request: Request, debug: int = 0):
    user, resp = _guard(request, "use_inbox")
    if resp:
        return resp
    if debug and config.can(user["role"], "manage_settings"):
        import json
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(json.dumps({
            "conversations_enabled": config.charlie_conversations_enabled(),
            "charlie_enabled": charlie.enabled(),
            "ghl_contacts_enabled": config.ghl_contacts_enabled(),
            "email_send_enabled": config.email_send_enabled(),
            "escalation_email": config.INBOX_ESCALATION_EMAIL,
            "webhook_secret_set": bool(config.GHL_WEBHOOK_SECRET),
            "open_needing_attention": db.count_inbox_attention(),
            "last_inbound_webhook": db.get_setting("inbox_last_webhook"),
        }, indent=2, default=str))
    return templates.TemplateResponse(
        "inbox.html",
        _ctx(request, user,
             charlie_name=config.CHARLIE_NAME,
             conversations_enabled=config.charlie_conversations_enabled(),
             open_convos=db.list_inbox(status="open"),
             closed_convos=db.list_inbox(status="closed", limit=25),
             fmt_dt=reminders.format_iso,
             flash=request.session.pop("inbox_flash", None)),
    )


@app.post("/inbox/{convo_id}/send")
def inbox_send(request: Request, convo_id: int, body: str = Form(...)):
    user, resp = _guard(request, "use_inbox")
    if resp:
        return resp
    result = inbox_svc.send_reply(convo_id, body, actor=user["email"])
    request.session["inbox_flash"] = ({"ok": True, "msg": f"Reply sent by {config.CHARLIE_NAME}."}
                                      if result["ok"]
                                      else {"ok": False, "msg": result["error"]})
    return RedirectResponse("/inbox", status_code=303)


@app.post("/inbox/{convo_id}/direct")
def inbox_direct(request: Request, convo_id: int, direction: str = Form(...)):
    user, resp = _guard(request, "use_inbox")
    if resp:
        return resp
    result = inbox_svc.direct(convo_id, direction, actor=user["email"])
    if result["ok"]:
        msg = (f"{config.CHARLIE_NAME} drafted a new reply — review and send it below."
               if result["outcome"] == "draft"
               else f"{config.CHARLIE_NAME} still needs a hand on this one.")
        for w in result.get("warnings", []):
            msg += f" ⚠️ {w}"
        request.session["inbox_flash"] = {"ok": True, "msg": msg}
    else:
        request.session["inbox_flash"] = {"ok": False, "msg": result["error"]}
    return RedirectResponse("/inbox", status_code=303)


@app.post("/inbox/{convo_id}/takeover")
def inbox_takeover(request: Request, convo_id: int):
    user, resp = _guard(request, "use_inbox")
    if resp:
        return resp
    inbox_svc.take_over(convo_id, actor=user["email"])
    request.session["inbox_flash"] = {"ok": True, "msg": "You've taken this over — "
                                      f"{config.CHARLIE_NAME} will step back and it's closed."}
    return RedirectResponse("/inbox", status_code=303)


@app.post("/webhook/ghl/inbound")
async def ghl_inbound_webhook(request: Request):
    """
    GoHighLevel posts an inbound text (a contact's reply) here. Protect with the
    shared secret (?secret=… or X-Webhook-Secret). Field names vary by GHL setup,
    so we match the common ones. Charlie drafts a reply or hands off to the Inbox;
    nothing is sent to the contact without a team member's click.
    """
    if config.GHL_WEBHOOK_SECRET:
        provided = request.query_params.get("secret") or request.headers.get("x-webhook-secret", "")
        if provided != config.GHL_WEBHOOK_SECRET:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "expected JSON"}, status_code=400)

    # Only act on inbound messages (ignore our own outbound echoes if GHL sends them).
    direction = str(_field(payload, "direction", "type", "messageType") or "").lower()
    if direction and ("out" in direction):
        return {"status": "ignored_outbound"}

    phone = _field(payload, "phone", "from", "CallFrom", "contact_phone", "number")
    text = _field(payload, "message", "body", "text", "messageBody", "sms") or ""
    contact_id = _field(payload, "contact_id", "contactId", "contactID")
    name = _field(payload, "full_name", "contact_name", "name")
    if not name:
        name = f"{_field(payload, 'first_name') or ''} {_field(payload, 'last_name') or ''}".strip() or None
    email = _field(payload, "email", "contact_email")

    # Stash the raw payload (redacted) so /inbox?debug=1 can confirm the shape.
    try:
        import json as _json
        db.set_setting("inbox_last_webhook", _json.dumps(granola._redact(payload))[:4000])
    except Exception:  # noqa: BLE001
        pass

    if not (phone or contact_id) or not str(text).strip():
        return JSONResponse({"status": "ignored_incomplete"}, status_code=200)

    out = inbox_svc.handle_inbound(phone=str(phone) if phone else None, text=str(text),
                                   contact_id=str(contact_id) if contact_id else None,
                                   name=name, email=email)
    return {"status": "ok", "convo_id": out.get("convo_id"), "outcome": out.get("outcome")}


# --- Meetings (Granola notes: client consults + team meetings) ---------------
@app.get("/meetings", response_class=HTMLResponse)
def meetings_page(request: Request, debug: int = 0):
    user, resp = _guard(request, "view_meetings")
    if resp:
        return resp
    if debug and config.can(user["role"], "manage_settings"):
        import json
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(json.dumps(granola.debug(), indent=2, default=str))
    return templates.TemplateResponse(
        "meetings.html",
        _ctx(request, user,
             granola_ok=config.granola_enabled(),
             can_manage=config.can(user["role"], "manage_meetings"),
             search_enabled=config.ghl_contacts_enabled(),
             pending=db.list_meetings(category="client", status="pending"),
             confirmed=db.list_meetings(category="client", status="confirmed", limit=50),
             team=db.list_meetings(category="team", limit=50),
             fmt_dt=reminders.format_iso,
             flash=request.session.pop("meetings_flash", None)),
    )


@app.post("/meetings/sync")
def meetings_sync(request: Request):
    user, resp = _guard(request, "manage_meetings")
    if resp:
        return resp
    result = meetings_svc.sync()
    if result["ok"]:
        msg = (f"Synced Granola — {result['new_client']} new consult(s) in the queue, "
               f"{result['new_team']} new team meeting(s) filed.")
        if not result["new_client"] and not result["new_team"]:
            msg = "Synced Granola — nothing new since last time."
        for w in result.get("warnings", []):
            msg += f" ⚠️ {w}"
        request.session["meetings_flash"] = {"ok": True, "msg": msg}
    else:
        request.session["meetings_flash"] = {"ok": False, "msg": result["error"]}
    return RedirectResponse("/meetings", status_code=303)


@app.post("/meetings/{meeting_id}/confirm")
def meetings_confirm(
    request: Request,
    meeting_id: int,
    contact_id: str = Form(""),
    name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
):
    user, resp = _guard(request, "manage_meetings")
    if resp:
        return resp
    result = meetings_svc.confirm(
        meeting_id, actor=user["email"], contact_id=contact_id,
        name=name, phone=phone, email=email,
    )
    if result["ok"]:
        msg = (f"Consult filed to {result['client_name']}'s record — note added to "
               "GoHighLevel and transcript saved for Charlie.")
        for w in result.get("warnings", []):
            msg += f" ⚠️ {w}"
        request.session["meetings_flash"] = {"ok": True, "msg": msg}
    else:
        request.session["meetings_flash"] = {"ok": False, "msg": result["error"]}
    return RedirectResponse("/meetings", status_code=303)


@app.post("/meetings/{meeting_id}/dismiss")
def meetings_dismiss(request: Request, meeting_id: int):
    user, resp = _guard(request, "manage_meetings")
    if resp:
        return resp
    db.dismiss_meeting(meeting_id, by=user["email"])
    request.session["meetings_flash"] = {"ok": True, "msg": "Consult dismissed from the queue."}
    return RedirectResponse("/meetings", status_code=303)


# --- Ask Charlie (AI assistant) ----------------------------------------------
@app.get("/charlie", response_class=HTMLResponse)
def charlie_page(request: Request, debug: int = 0):
    user, resp = _guard(request, "use_charlie")
    if resp:
        return resp
    if debug and config.can(user["role"], "manage_settings"):
        import json
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(json.dumps(charlie.debug(), indent=2, default=str))
    return templates.TemplateResponse(
        "charlie.html",
        _ctx(request, user,
             charlie_name=config.CHARLIE_NAME,
             charlie_enabled=charlie.enabled(),
             obsidian_ok=obsidian.is_configured(),
             brain_ready=charlie.brain_ready(),
             history=db.list_charlie_messages(user["email"]),
             pending_action=db.latest_pending_action(user["email"]),
             error=request.session.pop("charlie_error", None),
             flash=request.session.pop("charlie_flash", None)),
    )


@app.post("/charlie/setup-brain")
def charlie_setup_brain(request: Request):
    user, resp = _guard(request, "manage_settings")
    if resp:
        return resp
    result = charlie.setup_brain()
    if result["ok"]:
        made = result["created"]
        msg = (f"Charlie's brain is ready in Obsidian at {result['brain']}. "
               + (f"Created: {', '.join(made)}." if made else "Everything was already in place."))
        request.session["charlie_flash"] = {"ok": True, "msg": msg}
    else:
        request.session["charlie_flash"] = {"ok": False, "msg": result["error"]}
    return RedirectResponse("/charlie", status_code=303)


@app.post("/charlie/ask")
def charlie_ask(request: Request, question: str = Form(...)):
    user, resp = _guard(request, "use_charlie")
    if resp:
        return resp
    q = (question or "").strip()
    if q:
        history = db.list_charlie_messages(user["email"])
        db.add_charlie_message(user["email"], "user", q)
        result = charlie.ask(q, history)
        if result["ok"]:
            db.add_charlie_message(user["email"], "charlie", result["answer"])
            action = result.get("action")
            if action:
                db.add_charlie_action(
                    user["email"], channel=action["channel"], recipient=action["to"],
                    body=action["body"], subject=action.get("subject"))
        else:
            request.session["charlie_error"] = result["error"]
    return RedirectResponse("/charlie", status_code=303)


@app.post("/charlie/action/{action_id}/send")
def charlie_action_send(
    request: Request,
    action_id: int,
    recipient: str = Form(...),
    subject: str = Form(""),
    body: str = Form(...),
):
    user, resp = _guard(request, "use_charlie")
    if resp:
        return resp
    action = db.get_charlie_action(action_id)
    if not action or action["user_email"] != user["email"].lower() or action["status"] != "pending":
        return RedirectResponse("/charlie", status_code=303)

    recipient, subject, body = recipient.strip(), subject.strip(), body.strip()
    try:
        if not recipient:
            raise ValueError("Add a recipient before sending.")
        if action["channel"] == "email":
            mailer.send_email(recipient, subject, body)
            note = f"✅ Sent the email to {recipient}."
        else:  # sms via GHL — resolve the phone to a contact, then send
            contact_id = action["contact_id"]
            if not contact_id:
                contact = ghl.upsert_contact(config.reminder_location_id(), name=recipient, phone=recipient)
                contact_id = contact["id"]
            ghl.send_sms(contact_id, body)
            note = f"✅ Sent the text to {recipient}."
            # Track the thread so the contact's reply lands in Charlie's Inbox.
            try:
                inbox_svc.start_from_outreach(phone=recipient, body=body,
                                              contact_id=contact_id)
            except Exception:  # noqa: BLE001 - inbox tracking must not fail the send
                pass
        db.set_charlie_action_status(action_id, "sent", note)
        db.add_charlie_message(user["email"], "charlie", note)
    except Exception as exc:  # noqa: BLE001
        db.set_charlie_action_status(action_id, "failed", str(exc))
        request.session["charlie_error"] = f"Couldn't send: {exc}"
    return RedirectResponse("/charlie", status_code=303)


@app.get("/charlie/log", response_class=HTMLResponse)
def charlie_log(request: Request):
    user, resp = _guard(request, "use_charlie")
    if resp:
        return resp
    return templates.TemplateResponse(
        "charlie_log.html",
        _ctx(request, user,
             charlie_name=config.CHARLIE_NAME,
             actions=db.list_charlie_actions(),
             fmt_dt=reminders.format_iso),
    )


@app.post("/charlie/action/{action_id}/cancel")
def charlie_action_cancel(request: Request, action_id: int):
    user, resp = _guard(request, "use_charlie")
    if resp:
        return resp
    action = db.get_charlie_action(action_id)
    if action and action["user_email"] == user["email"].lower() and action["status"] == "pending":
        db.set_charlie_action_status(action_id, "cancelled", "Cancelled by team member.")
        db.add_charlie_message(user["email"], "charlie", "Okay — I won't send that.")
    return RedirectResponse("/charlie", status_code=303)


@app.post("/charlie/clear")
def charlie_clear(request: Request):
    user, resp = _guard(request, "use_charlie")
    if resp:
        return resp
    db.clear_charlie_messages(user["email"])
    return RedirectResponse("/charlie", status_code=303)


# --- Message inbox -----------------------------------------------------------
# A transcript line looks like "Speaker label: what they said". We split on the
# FIRST colon so labels that contain their own dash/hyphen survive intact
# (e.g. "Virtual Receptionist - PEI:"). The label is then classified below.
_SPEAKER_RE = re.compile(r"^\s*(?P<label>[^:\n]{1,50}):\s*(?P<said>.*)$")
# Which side of the conversation a speaker label belongs to.
_AGENT_RE = re.compile(r"receptionist|assistant|\bagent\b|\bai\b|\bbot\b|virtual", re.I)
_CALLER_RE = re.compile(r"\byou\b|caller|customer|\bclient\b|contact|guest|\buser\b", re.I)


def _parse_transcript(text: str, caller_name: Optional[str] = None) -> list[dict]:
    """
    Turn a call transcript into a list of conversation turns:
    [{role: 'agent'|'caller'|'other', label: str, text: str}, ...]
    so the page can show who said what.

    The agent side keeps its real label from the transcript (e.g.
    "Virtual Receptionist - PEI"); the caller side is shown as the caller's
    name when we know it, instead of a generic "You"/"Caller".
    """
    if not text:
        return []
    caller_label = (caller_name or "").strip() or "Caller"
    turns: list[dict] = []
    current = None
    for line in text.splitlines():
        m = _SPEAKER_RE.match(line)
        speaker = m.group("label").strip() if m else ""
        if m and (_AGENT_RE.search(speaker) or _CALLER_RE.search(speaker)):
            said = m.group("said").strip()
            if _AGENT_RE.search(speaker):
                role, label = "agent", speaker
            else:
                role, label = "caller", caller_label
            current = {"role": role, "label": label, "text": said}
            turns.append(current)
        elif line.strip():
            if current is not None:
                current["text"] += "\n" + line.strip()
            else:
                turns.append({"role": "other", "label": "", "text": line.strip()})
    return turns


@app.get("/messages", response_class=HTMLResponse)
def messages_inbox(request: Request, status: str = "new"):
    user, resp = _guard(request, "view_messages")
    if resp:
        return resp
    status_filter = None if status == "all" else status
    messages = db.list_messages(status_filter)
    for m in messages:
        turns = _parse_transcript(m.get("transcript") or "", m.get("client_name"))
        m["turns"] = turns
        m["is_conversation"] = any(t["role"] in ("agent", "caller") for t in turns)
    return templates.TemplateResponse(
        "messages.html",
        _ctx(request, user, messages=messages, active_filter=status,
             status_counts=db.status_breakdown()),
    )


@app.post("/messages/{message_id}/respond")
def respond_message(request: Request, message_id: int):
    user, resp = _guard(request, "respond_messages")
    if resp:
        return resp
    db.mark_message_responded(message_id, user["email"])
    return RedirectResponse("/messages", status_code=303)


# --- Team management (Super Admin / Spa Manager) -----------------------------
def _may_manage(actor: dict, target: dict) -> bool:
    """A Spa Manager can manage Team Members only; Super Admin can manage anyone."""
    if actor["role"] == "super_admin":
        return True
    if actor["role"] == "spa_manager":
        return target["role"] == "team_member"
    return False


@app.get("/admin/users", response_class=HTMLResponse)
def users_page(request: Request):
    user, resp = _guard(request, "manage_users")
    if resp:
        return resp
    return templates.TemplateResponse(
        "admin_users.html", _ctx(request, user, users=db.list_users())
    )


@app.post("/admin/users/role")
def change_role(request: Request, email: str = Form(...), role: str = Form(...)):
    actor, resp = _guard(request, "manage_users")
    if resp:
        return resp
    target = db.get_user_by_email(email)
    if target and role in config.ROLES and _may_manage(actor, target):
        # A Spa Manager may never promote someone to Super Admin.
        if actor["role"] == "super_admin" or role == "team_member":
            db.set_user_role(email, role)
    return RedirectResponse("/admin/users", status_code=303)


@app.post("/admin/users/active")
def toggle_active(request: Request, email: str = Form(...), active: str = Form(...)):
    actor, resp = _guard(request, "manage_users")
    if resp:
        return resp
    target = db.get_user_by_email(email)
    # No one can disable their own account (avoid locking yourself out).
    if target and _may_manage(actor, target) and target["email"] != actor["email"]:
        db.set_user_active(email, active == "true")
    return RedirectResponse("/admin/users", status_code=303)


# --- GoHighLevel webhook: after-hours call transcripts -----------------------
def _norm(key: str) -> str:
    """Reduce a field name to just its letters/numbers, lowercased, so that
    'Full Name', 'full_name' and 'fullName' all match."""
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


def _field(payload: dict, *names):
    """Return the first non-empty value whose key matches any of `names`,
    ignoring capitalization, spaces, and underscores."""
    normalized = {_norm(k): v for k, v in payload.items()}
    for n in names:
        value = normalized.get(_norm(n))
        if value not in (None, ""):
            return value
    return None


@app.post("/webhook/ghl/call")
async def ghl_call_webhook(request: Request):
    """
    GoHighLevel's AI receptionist posts a completed call here. Protected by a
    shared secret (set GHL_WEBHOOK_SECRET and include it as ?secret=... or the
    X-Webhook-Secret header). Field names vary by GHL setup, so we look for the
    common ones and keep the whole payload as the transcript if unsure.
    """
    if config.GHL_WEBHOOK_SECRET:
        provided = request.query_params.get("secret") or request.headers.get(
            "x-webhook-secret", ""
        )
        if provided != config.GHL_WEBHOOK_SECRET:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "expected JSON"}, status_code=400)

    phone = _field(payload, "CallFrom", "phone", "caller_number", "from") or "unknown"
    name = _field(payload, "Full Name", "contact_name", "full_name", "name")
    if not name:
        first = _field(payload, "first_name") or ""
        last = _field(payload, "last_name") or ""
        name = f"{first} {last}".strip() or None
    transcript = _field(
        payload, "Transcript", "call_transcript", "message", "body"
    ) or str(payload)
    summary = _field(payload, "summary", "call_summary")
    duration = _field(payload, "Duration", "call_duration")
    ghl_call_id = _field(payload, "call_id", "id", "messageId", "message_id")

    client = db.get_or_create_client(phone, name)
    vault_file = None
    try:
        vault_file = obsidian.write_call_transcript(
            phone=phone, transcript=transcript, caller_name=name,
            summary=summary, duration=duration,
        )
    except Exception:  # noqa: BLE001 - vault issue must not drop the message
        pass
    try:
        message_id = db.add_message(
            client_id=client["id"],
            transcript=transcript,
            summary=summary,
            duration=str(duration) if duration is not None else None,
            obsidian_file=vault_file,
            ghl_call_id=str(ghl_call_id) if ghl_call_id else None,
        )
    except sqlite3.IntegrityError:
        # We've already recorded this exact call (duplicate ghl_call_id).
        return {"status": "duplicate_ignored"}

    return {"status": "saved", "message_id": message_id, "obsidian_file": vault_file}
