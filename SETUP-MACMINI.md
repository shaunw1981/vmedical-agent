# Spa Dashboard — Setup guide (Build #1)

A step-by-step guide written for **non-developers**. By the end you'll have a
team **dashboard** running on the Mac Mini, that the team logs into with
**Google**, showing an **after-hours phone-message inbox**. Each call from
GoHighLevel's AI receptionist is filed into the client's **Obsidian** record and
shown in the dashboard to mark "responded."

There are three access levels: **Super Admin**, **Spa Manager**, **Team Member**.

> This is the first build. Client records, in-person consult notes (Granola), and
> more agents will be added as new sections later — the foundation is built for it.

**Time:** about an hour the first time (most of it is the Google + web-address
setup, which you only do once).

---

## The big picture

```
  GoHighLevel AI receptionist ─▶ Dashboard (on the Mac Mini) ─▶ Obsidian vault
        (after-hours calls)         team logs in with Google        (the brain)
                                     sees + responds to messages
```

Everything runs and is stored on the Mac Mini. A secure "tunnel" gives it a
private web address so the team can log in from anywhere and GoHighLevel can send
calls in.

We'll do this in five parts:
1. Put the project on the Mac and install it.
2. Give it a secure web address (Cloudflare Tunnel).
3. Turn on Google Sign-in.
4. Point it at the Obsidian vault.
5. Connect the GoHighLevel after-hours calls.

---

## Part 1 — Install on the Mac Mini

1. Make sure **Python 3** is installed (if not, get it from
   https://www.python.org/downloads/ and run the installer).
2. Download the project: on GitHub, green **Code** button → **Download ZIP**.
   Unzip it into **Documents** and rename the folder to `vmedical-agent`.
3. Open the `vmedical-agent/macmini` folder and **double-click `install.command`**.
   - If macOS blocks it: **right-click → Open → Open** (once).
   - It sets everything up and makes the dashboard start automatically.

The dashboard is now running on the Mac at `http://localhost:8000`, but we still
need to give it a web address and turn on Google login before the team can use it.

---

## Part 2 — Give it a secure web address (Cloudflare Tunnel)

This creates a private, secure `https://` address that points to the dashboard on
the Mac — without opening up your internet router. It's free.

1. Create a free account at https://www.cloudflare.com and add a domain you own
   (or buy a cheap one there, ~$10/yr). A subdomain like `spa.yourdomain.com`
   will be the dashboard address.
2. On the Mac Mini, install the Cloudflare tunnel tool. Open **Terminal** and
   paste:
   ```
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   brew install cloudflared
   ```
   (The first line installs "Homebrew," a helper for installing tools. Follow any
   on-screen prompts.)
3. Connect it and create the tunnel:
   ```
   cloudflared tunnel login
   cloudflared tunnel create spa-dashboard
   cloudflared tunnel route dns spa-dashboard spa.yourdomain.com
   ```
4. Tell me your chosen address (e.g. `spa.yourdomain.com`) and I'll give you the
   exact small config file + the command to keep the tunnel running automatically.
   (It's a couple of lines; I kept it out of here so we use your real domain.)

> **Why this step?** Google login and GoHighLevel both need a real `https://`
> address to talk to. The tunnel provides that while keeping everything running
> on your Mac.

---

## Part 3 — Turn on Google Sign-in

1. Go to https://console.cloud.google.com → create a project (name it "Spa
   Dashboard").
2. **APIs & Services → OAuth consent screen:** choose **Internal** (if the spa
   uses Google Workspace) so only their team can sign in. Fill in the app name
   and your email.
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID:**
   - Application type: **Web application**
   - **Authorized redirect URI:** `https://spa.yourdomain.com/auth/callback`
     (use your real tunnel address from Part 2)
   - Create it, then **copy the Client ID and Client Secret**.
4. On the Mac, open the settings file and fill it in:
   ```
   open -e ~/Documents/vmedical-agent/.env
   ```
   Set these lines (use your real values):
   ```
   BASE_URL=https://spa.yourdomain.com
   GOOGLE_CLIENT_ID=...(from step 3)...
   GOOGLE_CLIENT_SECRET=...(from step 3)...
   ALLOWED_EMAIL_DOMAIN=yourspadomain.com     # only these accounts can log in
   SUPER_ADMIN_EMAIL=you@yourspadomain.com     # this is YOU (the owner)
   SESSION_SECRET=...(run the command in the .env comments to generate one)...
   ```
5. Restart the app:
   ```
   launchctl unload ~/Library/LaunchAgents/com.vmedical-agent.plist
   launchctl load ~/Library/LaunchAgents/com.vmedical-agent.plist
   ```

Now visit `https://spa.yourdomain.com` — you should get a **Sign in with Google**
screen. Sign in with your own account: because your email is `SUPER_ADMIN_EMAIL`,
you'll come in as **Super Admin**. Everyone else who signs in starts as a **Team
Member**, and you can change their level on the **Team** page.

---

## Part 4 — Point it at the Obsidian vault

In the same `.env` file, set the vault folder path (find it in Obsidian →
Manage vaults):
```
OBSIDIAN_VAULT_PATH=/Users/frontdesk/Documents/GlowMedSpaVault
```
Restart the app (same two commands as above). Call transcripts will now be filed
under `vMedical Agent → Clients → <caller> → Calls` in the vault.

---

## Part 5 — Connect the GoHighLevel after-hours calls

We want GHL's AI receptionist to send each completed after-hours call to the
dashboard.

1. First, pick a webhook password and put it in `.env`:
   ```
   GHL_WEBHOOK_SECRET=some-long-made-up-password
   ```
   Restart the app. Your webhook address is then:
   ```
   https://spa.yourdomain.com/webhook/ghl/call?secret=some-long-made-up-password
   ```
2. In GoHighLevel, in the **Workflow** that handles after-hours calls / the AI
   receptionist, add a **Webhook** action:
   - Method: **POST**
   - URL: the address above
   - Send the call fields — at minimum the **caller phone number** and the **call
     transcript** (and the caller name and a call ID if available).
3. Because every GHL setup names fields a little differently, do a test call and
   then tell me — I'll confirm the field mapping so the caller name, phone, and
   transcript land in the right place. The receiving end is already built and
   secured; this is just matching your workflow's field names.

**Test it yourself** any time with a fake call (paste into Terminal, using your
real address + secret):
```bash
curl -X POST "https://spa.yourdomain.com/webhook/ghl/call?secret=some-long-made-up-password" \
  -H "Content-Type: application/json" \
  -d '{"phone":"902-555-0100","contact_name":"Test Caller","transcript":"Testing the after-hours line."}'
```
Then refresh the dashboard's **Messages** tab — the test call should appear as
**New**, and a note should show up in Obsidian under that caller.

---

## The three access levels

| Level          | Can do                                                              |
|----------------|--------------------------------------------------------------------|
| **Super Admin**| Everything, including managing all team members and settings.       |
| **Spa Manager**| See/respond to messages; manage Team Members (not other admins).    |
| **Team Member**| See and respond to phone messages.                                  |

New people appear on the **Team** page automatically after they sign in once;
a Super Admin or Spa Manager sets their level there. (We'll attach more sections
to these levels as we add features.)

---

## Everyday commands (Terminal on the Mac Mini)

| I want to...          | Do this                                                                 |
|-----------------------|-------------------------------------------------------------------------|
| Restart the dashboard | `launchctl unload ~/Library/LaunchAgents/com.vmedical-agent.plist && launchctl load ~/Library/LaunchAgents/com.vmedical-agent.plist` |
| Change settings       | `open -e ~/Documents/vmedical-agent/.env`  (restart after)              |
| See the app log       | `open ~/Documents/vmedical-agent/data/app.log`                          |

## Backups
- The **Obsidian vault** is just a folder — back it up (Time Machine / a copy).
- The dashboard's data is in `~/Documents/vmedical-agent/data/app.db`.

## Keep the Mac always on
- The app keeps the Mac awake while running. For extra safety, **System Settings
  → Users & Groups → Automatically log in** as the front-desk account, so it
  comes back on its own after a power cut.

---

## Stuck?
Tell me which part number you're on and what you saw on screen — especially for
the Cloudflare Tunnel and Google steps, where I can hand you the exact lines for
your real domain.
