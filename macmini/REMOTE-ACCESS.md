# Coding & deploying the Valley Medical dashboard remotely

The Mac Mini in the clinic is a **runtime box** — it only *runs* the app, Ollama,
and the Cloudflare tunnel. All **development happens from the Blue Cow office**
using your own Claude Code account, against the GitHub repo. Claude Code is never
installed or logged in on the client's Mac.

Code flows one direction:

    Claude Code (your office) ──▶ GitHub (shaunw1981/vmedical-agent) ──▶ clinic Mac

The clinic Mac only ever *pulls finished code down*. It never originates code.

---

## One-time setup

### 1. Private network to the Mac — Tailscale

This lets you reach the clinic Mac from your office with no port-forwarding and
nothing exposed to the public internet. Everything is end-to-end encrypted.

1. Make a Tailscale account (free tier is fine): https://tailscale.com
2. Install Tailscale on the **clinic Mac** and sign in to your account.
   Give the machine a clear name, e.g. `valley-macmini`.
3. Install Tailscale on your **office machine** and sign in to the same account.
4. Confirm they see each other: `tailscale status` lists both.

### 2. Turn on the Mac's SSH server — Remote Login

On the clinic Mac: **System Settings → General → Sharing → Remote Login = ON**
(limit "Allow access for" to the `agent` user).

### 3. Passwordless login from your office — SSH key

From your **office machine**:

    ssh-keygen -t ed25519            # if you don't already have a key
    ssh-copy-id agent@valley-macmini # pushes your public key to the Mac

Now test it:

    ssh agent@valley-macmini 'echo connected; hostname'

You should connect with no password. (`valley-macmini` is the Tailscale name; a
Tailscale IP like `100.x.y.z` also works.)

---

## Day-to-day workflow

### Develop
Use Claude Code from your office exactly like today. Edit, commit, push to GitHub.

### Deploy (manual, when YOU decide)
From your office, one command pulls the latest code onto the clinic Mac and
restarts it — no one needs to be at the machine:

    ssh agent@valley-macmini 'bash ~/vmedical-agent/macmini/deploy-remote.sh'

It prints `OK — dashboard is live…` with a health check, or `FAILED` with a
reason, and exits non-zero on failure. Your `.env`, database, and Obsidian
vault are never touched.

**First-time bootstrap** (before `deploy-remote.sh` exists on the Mac), run once:

    ssh agent@valley-macmini 'curl -fsSL https://raw.githubusercontent.com/shaunw1981/vmedical-agent/main/macmini/deploy-remote.sh | bash'

After that first run the script lives on the Mac and you use the short form above.

### Handy aliases (optional)
Add to `~/.zshrc` on your office machine:

    alias vm-ssh='ssh agent@valley-macmini'
    alias vm-deploy='ssh agent@valley-macmini "bash ~/vmedical-agent/macmini/deploy-remote.sh"'
    alias vm-restart='ssh agent@valley-macmini "launchctl kickstart -k gui/$(ssh agent@valley-macmini id -u)/com.vmedical-agent"'

### Other remote tasks
- **Restart only:** `ssh agent@valley-macmini 'launchctl kickstart -k gui/$(id -u)/com.vmedical-agent'`
- **Tail the app log:** `ssh agent@valley-macmini 'tail -n 50 ~/Library/Logs/vmedical-agent.log'` (adjust path to your log)
- **Check health:** `ssh agent@valley-macmini 'curl -s localhost:8000/health'`
- **Edit .env, then restart:** edit over SSH, then run the restart command above.

---

## Notes
- **Claude Code is NOT needed on the clinic Mac** — it never was. Safe to uninstall it there.
- The public site keeps working through the existing Cloudflare tunnel regardless of SSH.
- Tailscale + Remote Login is for *you*, privately; it does not expose the Mac publicly.
- If you ever retire Tailscale, remember Remote Login is still on — turn it off too.
