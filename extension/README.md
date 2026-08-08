# Valley Medical — Appointment Reminders (Chrome extension)

A small popup that lets the team look up a client (or add a new one) and
schedule an appointment reminder, without opening the full dashboard. It talks
to the dashboard's JSON API:

- `GET /api/appointment-types` — the type dropdown (also used to verify sign-in)
- `GET /api/contacts/search?q=` — client lookup
- `POST /api/reminders` — creates/updates the contact in GoHighLevel, drops them
  into the mapped workflow, and books the appointment (same logic as the website)

## One-time server setup

The extension signs in with an **access key**. On the Mac, set one in `.env`:

```
DASHBOARD_API_KEY=<a long random value>
```

Generate one with:

```
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then run `restart.command`. (The dashboard already allows the extension to call
`/api/*` via CORS — no other server change needed.)

## Install the extension (per team member)

1. Open Chrome → `chrome://extensions`.
2. Turn on **Developer mode** (top-right).
3. Click **Load unpacked** and choose this `extension/` folder.
4. Pin the "Appointment Reminders" icon to the toolbar.

## Sign in

Click the icon and enter:

- **Dashboard address** — e.g. `https://spa.example.com` (the same URL you use
  for the dashboard).
- **Access key** — the `DASHBOARD_API_KEY` value from above.
- **Your email** — so reminders you schedule are attributed to you.

These are stored locally in the browser; you stay signed in until you click
**Log out**.

## Use it

1. Type a name, email, or phone in **Find a client**.
2. Click a result to load their details — or click **+ Add a new client** and
   type them in (whatever you searched is used as a starting point).
3. Pick the **appointment type** and **date & time**, then **Schedule reminder**.

New clients are created in GoHighLevel automatically on schedule, so lookup +
add + reminder all happen in one step.

## Notes

- The access key is shared; individual attribution comes from the **Your email**
  field, sent with each reminder.
- To publish to the Chrome Web Store later, this folder can be zipped as-is
  (Manifest V3). For internal use, "Load unpacked" is enough.
