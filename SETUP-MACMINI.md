# Spa Dashboard — Setup guide (Build #1)

**Written for non-developers.** Do the stages in order. There's a friendly,
tick-as-you-go version of this guide (with a progress bar) that you can keep open
on your phone — ask Shaun/Claude for the checklist link. This file is the backup
copy that lives on the Mac.

Total time: about an hour the first time. Only cost: a domain name (~$10/year).

Three double-click helpers live in the `macmini` folder so you rarely need
Terminal:
- **`install.command`** — sets everything up (Stage 1).
- **`open-settings.command`** — opens the settings file in TextEdit (Stage 5).
- **`restart.command`** — applies settings after you change them.

> First time you double-click any `.command` file, macOS may block it. Fix:
> right-click the file → **Open** → **Open**. You only do this once per file.

---

## Stage 0 — Gather these first
- The Mac Mini, on and online.
- Obsidian installed, with the client's vault opened once.
- The spa's Google account login.
- A credit card (for the domain).

## Stage 1 — Put the app on the Mac Mini
1. In Safari on the Mac, go to `github.com/shaunw1981/vmedical-agent`.
2. Green **Code** button → **Download ZIP**.
3. In **Downloads**, double-click the ZIP to unzip → folder `vmedical-agent-main`.
4. Move it into **Documents** and rename it to `vmedical-agent`.
5. Check Python: open **Terminal** (⌘Space → type Terminal), run
   `python3 --version`. If “command not found,” install from
   `python.org/downloads`, then retry.
6. In Finder: **Documents → vmedical-agent → macmini**, double-click
   **`install.command`**. Wait for **“Done!”**

**✓ Check:** open `http://localhost:8000` — you should see a “Sign in with
Google” screen (it won't log in until Stage 4; seeing it is the win).

## Stage 2 — Get a web address (domain)
1. Create a free account at `cloudflare.com` (used for the address *and* the
   secure connection).
2. **Domain Registration → Register Domain** → buy a name (~$10/yr).
3. Pick your dashboard address, e.g. **`dashboard.yourspa.com`**.

**✓ Check:** the domain appears in your Cloudflare account.

## Stage 3 — Connect the address to the Mac, securely (Cloudflare Tunnel)
1. In Cloudflare, open **Zero Trust** (`one.dash.cloudflare.com`). If prompted,
   pick the **Free** plan and make up a team name.
2. **Networks → Tunnels → Create a tunnel → Cloudflared → Next**.
3. Name it `spa-dashboard` → **Save tunnel**.
4. Choose **Mac**, copy the command shown, paste it into **Terminal** on the Mac,
   press Return.
   - If “command not found: cloudflared,” run these first, then paste the command
     again:
     ```
     /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
     brew install cloudflared
     ```
5. Wait until Cloudflare shows the connector **Connected** → **Next**.
6. Add the **Public Hostname**:
   - Subdomain: `dashboard`
   - Domain: your domain (dropdown)
   - Service Type: `HTTP`  ·  URL: `localhost:8000`
   - **Save tunnel**.

**✓ Check:** on your phone, open `https://dashboard.yourspa.com` — you see the
“Sign in with Google” screen. (This is the trickiest stage — send a screenshot if
stuck.)

## Stage 4 — Turn on Google Sign-in
1. `console.cloud.google.com` → sign in with the spa's Google account.
2. Project dropdown → **New Project** → name `Spa Dashboard` → create + select.
3. Search **“OAuth consent screen”** → choose **Internal** (Workspace) or
   **External** → fill app name + your email → Save/Continue to the end.
4. Search **“Credentials”** → **Create Credentials → OAuth client ID**.
5. Application type **Web application**. Under **Authorized redirect URIs**, add:
   `https://dashboard.yourspa.com/auth/callback`  → **Create**.
6. Copy the **Client ID** and **Client secret** (used in Stage 5).

> Google's screens change often; look for **“OAuth consent screen”** and
> **“Credentials.”** Send a screenshot if you get lost.

## Stage 5 — Fill in the settings file
1. In **macmini**, double-click **`open-settings.command`** — the `.env` file
   opens in TextEdit.
2. Fill in (leave the rest as-is):
   ```
   BASE_URL=https://dashboard.yourspa.com
   GOOGLE_CLIENT_ID=...(Stage 4)...
   GOOGLE_CLIENT_SECRET=...(Stage 4)...
   ALLOWED_EMAIL_DOMAIN=yourspa.com
   SUPER_ADMIN_EMAIL=you@yourspa.com
   OBSIDIAN_VAULT_PATH=/Users/…/YourVault
   GHL_WEBHOOK_SECRET=some-long-made-up-password
   ```
   - `SESSION_SECRET` is already filled in by the installer — don't change it.
   - Find `OBSIDIAN_VAULT_PATH` in Obsidian → vault name (bottom-left) →
     **Manage vaults**.
3. Save (⌘S). If TextEdit added formatting, use **Format → Make Plain Text**.
4. Double-click **`restart.command`**. Wait ~10 seconds.

## Stage 6 — First login (you become Super Admin)
Go to `https://dashboard.yourspa.com` → **Sign in with Google** → use your own
spa email (the `SUPER_ADMIN_EMAIL`).

**✓ Check:** you see **Home / Messages / Team**, with **Super Admin** by your
name. If “Only … accounts can sign in,” fix `ALLOWED_EMAIL_DOMAIN` (Stage 5) and
restart.

## Stage 7 — Add the team
1. Each team member signs in with Google once (they start as Team Member).
2. On the **Team** page, set each person's access level and **Save**.

Access levels: **Super Admin** (everything), **Spa Manager** (messages + manage
Team Members), **Team Member** (see/respond to messages).

## Stage 8 — Connect GoHighLevel after-hours calls
1. Your webhook address:
   `https://dashboard.yourspa.com/webhook/ghl/call?secret=YOUR-PASSWORD`
   (the password is your `GHL_WEBHOOK_SECRET`).
2. In GHL's after-hours / AI-receptionist workflow, add a **Webhook** action
   (POST) to that URL, sending at least the caller **phone** and **transcript**
   (plus name + call id if available).
3. Make a **test call**, then send Claude what came through so the field mapping
   can be confirmed.

**✓ Check:** the test call shows as **New** in **Messages**, and a note appears
in Obsidian under **vMedical Agent → Clients → (caller) → Calls**.

---

## Everyday helpers
- Change settings: double-click **`open-settings.command`**, then
  **`restart.command`**.
- App log (if something seems off): `~/Documents/vmedical-agent/data/app.log`.

## Backups
- The **Obsidian vault** is a folder — back it up (Time Machine / a copy).
- Dashboard data: `~/Documents/vmedical-agent/data/app.db`.

## Keep the Mac always on
**System Settings → Users & Groups → Automatically log in** as the front-desk
account, so the dashboard comes back on its own after a power cut. (The app keeps
the Mac awake while running.)
