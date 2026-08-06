# vmedical-agent — Spa team dashboard

A dashboard + AI-agent platform for a med spa, running **locally on a Mac Mini**.
The team signs in with **Google**, and the shared **Obsidian vault** is the
"brain" where each client's history is filed (keyed by phone number).

**Build #1 (this repo):** after-hours phone flow — GoHighLevel's AI receptionist
posts each call to the dashboard; it's saved into Obsidian under the caller and
shown in a **message inbox** the team can mark "responded." Login + 3 access
levels (Super Admin / Spa Manager / Team Member) included.

- **Setting it up? → [SETUP-MACMINI.md](SETUP-MACMINI.md)** (written for
  non-developers).

## How it fits together

```
GoHighLevel AI receptionist ─▶ Dashboard (Mac Mini) ─▶ Obsidian vault (brain)
     after-hours calls            Google login,           per-client folders,
                                  3 roles, inbox           call transcripts
```

## Roadmap (designed for, not built yet)
- Client-record screens in the dashboard.
- In-person consults recorded → **Granola** notes → filed under the client in
  Obsidian and viewable in the dashboard.
- Additional agents/tools as new dashboard sections, each gated by the 3 roles.

## What's in here

| File / folder            | Purpose                                                      |
|--------------------------|--------------------------------------------------------------|
| `app.py`                 | The dashboard web app (routes, pages, GHL webhook).          |
| `auth.py`                | Google Sign-in + role assignment.                            |
| `config.py`              | Settings + the roles/permissions rules.                      |
| `db.py`                  | Local database: users, clients (by phone), messages.         |
| `obsidian.py`            | Files call transcripts into the vault, per client.           |
| `templates/`             | The dashboard pages.                                         |
| `macmini/`               | Double-click installer + auto-start for the Mac Mini.        |
| `SETUP-MACMINI.md`       | Full non-developer setup guide.                              |
| `.env.example`           | Settings template.                                           |

## Access levels

| Level        | Can do                                                       |
|--------------|--------------------------------------------------------------|
| Super Admin  | Everything, incl. managing all team members and settings.    |
| Spa Manager  | See/respond to messages; manage Team Members.                |
| Team Member  | See and respond to phone messages.                           |

## Privacy
Notes live only on the Mac (Obsidian vault + local database). Nothing is stored
in a third-party cloud. Med-spa client information is personal information under
Canadian privacy law (PIPEDA) — keep the Mac secured and access limited to the
team.

## Try it on your own computer (optional, no Google needed to browse)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env         # set OBSIDIAN_VAULT_PATH; Google can stay blank
uvicorn app:app --reload     # http://127.0.0.1:8000  (login needs Google set up)
```
