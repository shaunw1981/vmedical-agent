# Setting up vmedical-agent on the Mac Mini

A step-by-step guide written for **non-developers**. By the end, the Mac Mini at
the spa will quietly capture voicemail and appointment notes from GoHighLevel
and file them into the client's **Obsidian vault** — all stored locally on that
Mac.

**Roughly how long:** 30–45 minutes.
**What it costs:** nothing extra (it's your own Mac). Optional AI tidy-up uses
Anthropic and is off by default.

---

## How it all fits together (the big picture)

```
  GoHighLevel  ─▶  vmedical-agent  ─▶  Obsidian vault  ─▶  Staff read notes
  (voicemails,     (runs on the         (a folder of         in Obsidian
   appointments)   Mac Mini)            Markdown files)
```

- **The Mac Mini** is the always-on computer that runs the little app.
- **Obsidian** is the "brain" — every note becomes a text file in the vault, so
  staff can read, search, and link them.
- **Everything stays on the Mac.** Nothing is stored in the cloud. (The only
  thing that could ever leave is if you turn on optional AI tidy-up — see the
  end of this guide. It's off by default.)

---

## Before you start

You'll need, on the Mac Mini:

1. **Obsidian installed**, with the client's vault already opened once so the
   folder exists. To find the vault's folder path later: open Obsidian → click
   the vault name at the bottom-left → **Manage vaults** → it shows the folder.
2. **Python 3** installed. If it's not, download the macOS installer from
   https://www.python.org/downloads/ , run it, and click through the defaults.
3. About 30 minutes.

---

## Part 1 — Put the project on the Mac Mini

The simplest way, no developer tools needed:

1. Go to the project on GitHub:
   `https://github.com/shaunw1981/vmedical-agent`
2. Click the green **Code** button → **Download ZIP**.
3. Open the downloaded ZIP (it unzips to a folder like `vmedical-agent-main`).
4. Move that folder somewhere sensible, e.g. into **Documents**. Rename it to
   `vmedical-agent` if you like.

---

## Part 2 — Run the installer (one double-click)

1. Open the project folder, then open the **`macmini`** folder inside it.
2. **Double-click `install.command`.**
   - If macOS blocks it with *"cannot be opened because it is from an
     unidentified developer,"* **right-click** the file → **Open** → **Open**.
     (You only need to do this once.)
3. A black window opens and sets everything up. When it finishes it prints a
   **"Done!"** message. You can close the window.

The installer also set the app to **start automatically** and keep running —
even after the Mac restarts.

---

## Part 3 — Point it at the Obsidian vault

The app needs to know which folder is the client's vault.

1. Open the settings file. In the Terminal window (or a new one), or via Finder,
   open the file called **`.env`** in the project folder. Easiest way — run:
   ```
   open -e ~/Documents/vmedical-agent/.env
   ```
   (adjust the path if you put the folder elsewhere).
2. Find this line:
   ```
   OBSIDIAN_VAULT_PATH=/Users/USERNAME/Documents/SpaVault
   ```
   Replace it with the **real vault folder path** from Obsidian (the one you
   found in "Before you start"). For example:
   ```
   OBSIDIAN_VAULT_PATH=/Users/frontdesk/Documents/GlowMedSpaVault
   ```
3. Save the file (Cmd+S) and close it.
4. Restart the app so it picks up the change. Copy-paste this into Terminal:
   ```
   launchctl unload ~/Library/LaunchAgents/com.vmedical-agent.plist
   launchctl load ~/Library/LaunchAgents/com.vmedical-agent.plist
   ```

---

## Part 4 — Test that it works

**1. Open the notes page.** In a browser on the Mac Mini, go to:
```
http://localhost:8000
```
You should see a "Spa Notes" page (empty for now).

**2. Add a test note.** Paste this into Terminal:
```bash
curl -X POST http://localhost:8000/api/notes \
  -H "Content-Type: application/json" \
  -d '{"note_type":"voicemail","caller_name":"Test Caller","caller_phone":"902-555-0000","raw_text":"Just testing the system"}'
```

**3. Check both places:**
- Refresh `http://localhost:8000` — the test note should appear.
- Open **Obsidian** — inside the vault you'll now see a folder
  **`vMedical Agent → Voicemails`** with a note file for the test caller. 🎉

That confirms the whole chain works and notes are landing in the brain.

---

## Part 5 — Connecting GoHighLevel

This is the step that makes real voicemails/appointments flow in. Because the
Mac Mini sits behind the spa's internet router, the reliable approach is to have
the Mac **pull** from GoHighLevel on a schedule (rather than GHL pushing in).

You'll need two things from GoHighLevel:

1. **An API token** — in GoHighLevel: **Settings → (Private) Integrations →
   create one**, and copy the token.
2. **Your Location ID** — in GoHighLevel: **Settings → Business Info**, or the
   long ID in the web address when you're in that sub-account.

Put both into the `.env` file:
```
GHL_API_TOKEN=your-token-here
GHL_LOCATION_ID=your-location-id-here
```

Then tell me you've done this, and I'll finish wiring the pull so it runs
automatically every few minutes. (The connector is already built — it just
needs your account's exact settings confirmed, which is safest to do together.)

> Prefer GoHighLevel to send notes the moment a voicemail lands? That's also
> possible using a GHL "Webhook" action pointing at the app — but it needs a
> secure tunnel so the outside world can reach the Mac. The pull method above is
> simpler and needs no tunnel, so start there.

---

## Part 6 — Keep the Mac Mini always on

So notes keep flowing even if no one's touching the Mac:

1. **Prevent sleep:** the app already keeps the Mac awake while it runs (no
   setting needed). For belt-and-suspenders, go to **System Settings → Displays
   → Advanced** (or **Energy**) and turn on *"Prevent automatic sleeping when
   the display is off."*
2. **Auto-login after a power cut:** **System Settings → Users & Groups →
   Automatically log in as →** the front-desk account. This ensures the app
   comes back on its own if the Mac restarts.

---

## Everyday commands (bookmark these)

Run these in the **Terminal** app on the Mac Mini:

| I want to...                     | Do this                                                        |
|----------------------------------|----------------------------------------------------------------|
| See the notes                    | Open `http://localhost:8000` (or just use Obsidian)            |
| Restart the app                  | `launchctl unload ~/Library/LaunchAgents/com.vmedical-agent.plist && launchctl load ~/Library/LaunchAgents/com.vmedical-agent.plist` |
| Change settings                  | `open -e ~/Documents/vmedical-agent/.env` (restart after)     |
| See the app's log                | `open ~/Documents/vmedical-agent/data/app.log`                |

---

## Backups

Two easy things keep you safe:
- The **Obsidian vault** is just a folder — back it up like any folder (Time
  Machine, iCloud, a copy to a USB drive).
- The app also keeps a copy in `data/notes.db` inside the project folder.

---

## Optional — AI tidy-up (off by default)

Voicemail transcripts can be messy. The app can have Claude rewrite them into
clean, short notes ("Jane called to move her Thursday facial; callback
902-555-0100"). **This is the one feature that sends text off the Mac** (to
Anthropic), so it's **off by default** to keep everything local.

To turn it on, edit `.env`:
```
AI_CLEANUP=on
ANTHROPIC_API_KEY=sk-ant-your-key-here     # from https://console.anthropic.com
```
Then restart the app. Leave `AI_CLEANUP=off` to keep every note 100% local.

---

## If something's not working

- **Notes page won't open** → give it a minute after install; the app may still
  be starting. Check the log: `open ~/Documents/vmedical-agent/data/app.log`.
- **Notes save but don't appear in Obsidian** → the `OBSIDIAN_VAULT_PATH` in
  `.env` is probably wrong. Re-copy the exact folder path from Obsidian's
  "Manage vaults," fix `.env`, and restart the app.
- **Stuck on any step** → tell me the step number and what you saw, and I'll
  walk you through it.
