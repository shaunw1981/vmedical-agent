# Valley Medical — Reminders (Chrome Extension)

A small Chrome popup that schedules appointment reminders and post-visit
follow-ups in the Valley Medical dashboard, without opening the dashboard in a
tab. It talks to the same dashboard API the Reminders page uses.

## What it does

- **Search a patient** by name (autocomplete against the dashboard).
- **Add a new patient** inline when there's no record yet — it creates the
  record *and* uses it for the reminder.
- **Pick a service and date/time**, set how many days before to remind.
- **Edit the message** — email subject/body and the text message pre-fill from
  the per-service template with the patient's name, service, date and time
  filled in. "Reset to template" restores the default wording.
- **Optional review request** a chosen number of days after the visit.
- **Schedule** — the dashboard sends the email and/or text when due.

## Install (unpacked)

1. Open **chrome://extensions** in Chrome.
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and choose this `extension/` folder.
4. The bell icon appears in the toolbar. Pin it for easy access.

## First-time setup

1. Click the extension icon, then **Open settings** (or the ⚙ gear).
2. **Dashboard address:**
   - On the clinic Mac: `http://localhost:8000`
   - On a tablet or another computer (via Tailscale): `http://valley-macmini:8000`
3. **API key:** paste the dashboard's API key. This is the `DASHBOARD_API_KEY`
   value set in the dashboard's `.env` on the clinic Mac. Ask Blue Cow if you
   don't have it.
4. (Optional) **Your name** — tags who scheduled each reminder.
5. Click **Save & connect**. Chrome will ask permission to reach the dashboard
   address — allow it. The settings page confirms the connection.

Settings are stored on the device only (Chrome sync storage); the API key is
never sent anywhere except to your dashboard.

## Notes

- The extension needs network access to the dashboard address you enter. On a
  tablet that means Tailscale must be connected, same as opening the dashboard
  in a browser tab.
- Sending (email/text) is handled by the dashboard, using its existing mail and
  GoHighLevel setup — the extension only schedules.
- To point it at a different dashboard, open settings and change the address.

## API endpoints used

All require the `X-API-Key` header:

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/api/patients/search?q=` | Patient autocomplete |
| POST | `/api/patients` | Create a patient |
| GET  | `/api/appointment-types` | Service list |
| GET  | `/api/reminder-content?type_key=&name=&appt_at=` | Pre-fill message |
| POST | `/api/reminders` | Schedule the reminder |
