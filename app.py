"""
vmedical-agent — the team dashboard (Build #1).

Runs on the Mac Mini. The team signs in with Google, and (based on their role:
Super Admin / Spa Manager / Team Member) sees the after-hours phone-message
inbox. GoHighLevel's AI receptionist posts call transcripts to /webhook/ghl/call;
each one is filed into the Obsidian vault under the caller's number and shown in
the inbox for the team to mark "responded."

See SETUP-MACMINI.md for how to run it and connect Google + GoHighLevel.
"""

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import auth
import config
import db
import obsidian

app = FastAPI(title="vmedical-agent dashboard", version="3.0.0")
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# Make role/permission helpers available inside every template.
templates.env.globals.update(
    can=config.can, ROLE_LABELS=config.ROLE_LABELS, ROLES=config.ROLES
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


def _ctx(request: Request, user: dict, **extra) -> dict:
    """Shared template context (adds nav data like the unread count)."""
    base = {
        "request": request,
        "user": user,
        "new_count": db.count_new_messages(),
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
    return templates.TemplateResponse(
        "dashboard.html",
        _ctx(request, user, responded_count=len(db.list_messages("responded"))),
    )


# --- Message inbox -----------------------------------------------------------
@app.get("/messages", response_class=HTMLResponse)
def messages_inbox(request: Request, status: str = "new"):
    user, resp = _guard(request, "view_messages")
    if resp:
        return resp
    status_filter = None if status == "all" else status
    return templates.TemplateResponse(
        "messages.html",
        _ctx(
            request, user,
            messages=db.list_messages(status_filter),
            active_filter=status,
        ),
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

    phone = (
        payload.get("phone")
        or payload.get("caller_number")
        or payload.get("from")
        or "unknown"
    )
    name = (
        payload.get("contact_name")
        or payload.get("full_name")
        or f"{payload.get('first_name', '')} {payload.get('last_name', '')}".strip()
        or None
    )
    transcript = (
        payload.get("transcript")
        or payload.get("call_transcript")
        or payload.get("message")
        or payload.get("body")
        or str(payload)
    )
    summary = payload.get("summary")
    ghl_call_id = (
        payload.get("call_id") or payload.get("id") or payload.get("messageId")
    )

    client = db.get_or_create_client(phone, name)
    vault_file = obsidian.write_call_transcript(
        phone=phone, transcript=transcript, caller_name=name, summary=summary
    )
    try:
        message_id = db.add_message(
            client_id=client["id"],
            transcript=transcript,
            summary=summary,
            obsidian_file=vault_file,
            ghl_call_id=str(ghl_call_id) if ghl_call_id else None,
        )
    except sqlite3.IntegrityError:
        # We've already recorded this exact call (duplicate ghl_call_id).
        return {"status": "duplicate_ignored"}

    return {"status": "saved", "message_id": message_id, "obsidian_file": vault_file}
