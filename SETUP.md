# Setting up vmedical-agent on a DigitalOcean droplet

A step-by-step guide written for **non-developers**. Follow it top to bottom.
By the end you'll have your agent running 24/7 in the cloud, reachable over the
internet.

Take your time — you can't really break anything, and a droplet can be deleted
and re-created in minutes if something goes wrong.

**Roughly how long:** 30–45 minutes the first time.
**Roughly how much:** about **$6/month** for the smallest droplet.

---

## A quick note before you start (please read)

This project is a *medical-information* agent. A few important cautions:

- It gives **general information only** — it is not a doctor and must not be
  used to diagnose or treat anyone.
- **Do not put real patient information** (names, health records, etc.) into it
  unless you have proper legal/compliance measures in place (HIPAA, PIPEDA,
  etc.). A basic droplet is **not** a compliant environment for real patient
  data. Talk to a professional before going anywhere near real medical records.
- Keep your Anthropic API key secret. Anyone with it can spend your money.

---

## What you'll need first

1. A **DigitalOcean account** — sign up at https://www.digitalocean.com
   (they'll ask for a credit card).
2. An **Anthropic API key** — from https://console.anthropic.com →
   *Settings → API Keys*. It starts with `sk-ant-`. Copy it somewhere safe.
3. **10 minutes** of uninterrupted time.

That's it. You do **not** need to install anything on your own computer — every
command below runs on the droplet through a web-based terminal.

---

## Part 1 — Create the droplet (on the DigitalOcean website)

1. Log in to DigitalOcean.
2. Click the green **Create** button (top right) → **Droplets**.
3. **Choose a region:** pick the one closest to you (e.g. *Toronto* or
   *New York*).
4. **Choose an image:** under the *OS* tab, pick **Ubuntu** and leave the
   default version (e.g. `24.04 LTS`).
5. **Choose a size:**
   - Droplet Type: **Basic**
   - CPU options: **Regular** → the **$6/month** option
     (1 GB RAM / 1 CPU) is plenty to start.
6. **Choose Authentication Method:** select **Password** (simpler for
   non-developers).
   - Create a strong root password and **save it** somewhere safe — you'll need
     it in a moment. (SSH keys are more secure but more fiddly; password is fine
     to begin with.)
7. **Hostname:** you can rename it to `vmedical-agent` if you like.
8. Click **Create Droplet** at the bottom.

Wait about 30–60 seconds. When it's ready, you'll see your droplet with a
**public IP address** that looks like `164.92.xx.xx`. **Copy that IP address** —
this is your server's address on the internet.

---

## Part 2 — Log in to the droplet

You don't need any special software. Use DigitalOcean's built-in terminal:

1. Click your droplet's name.
2. Click the **Console** button (top right, sometimes labeled
   *Launch Droplet Console*).
3. A black terminal window opens in your browser. If it asks for a login,
   type `root`, press Enter, then type the password you created.
   (When typing the password, nothing shows on screen — that's normal. Just
   type it and press Enter.)

You're now "inside" your server. Everything from here is copy-paste.

> **Tip:** In the console, paste with **Ctrl+Shift+V** (or right-click →
> Paste). Regular Ctrl+V may not work in a terminal.

---

## Part 3 — Install and run your agent

Copy each block below into the console and press Enter. Wait for each one to
finish before doing the next.

**3a. Download your project from GitHub:**

```bash
apt-get update -y && apt-get install -y git
git clone https://github.com/shaunw1981/vmedical-agent.git
cd vmedical-agent
```

> Working from a specific branch instead of the main code? Add this after the
> `cd` line: `git checkout claude/digital-ocean-droplet-setup-c4ayj1`

**3b. Run the automatic setup script** (this does all the heavy lifting —
installs Python, sets up the service and the internet "front door"):

```bash
bash deploy/setup.sh
```

This takes a couple of minutes. When it finishes it will print a "Done!"
message.

**3c. Add your Anthropic API key.** The setup created a settings file; now put
your real key in it:

```bash
nano /opt/vmedical-agent/.env
```

A simple text editor opens. Find the line:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Replace `sk-ant-your-key-here` with your real key. Then save and exit:
press **Ctrl+O**, then **Enter**, then **Ctrl+X**.

**3d. Restart the service so it picks up your key:**

```bash
systemctl restart vmedical-agent
```

That's it — your agent is live. 🎉

---

## Part 4 — Check that it's working

**Test it on the server itself:**

```bash
curl http://localhost/health
```

You should see: `{"status":"ok","api_key_configured":true}`
(If `api_key_configured` says `false`, your key wasn't saved — redo step 3c.)

**Now ask it a real question:**

```bash
curl -X POST http://localhost/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What is a fever?"}'
```

You should get a helpful answer back within a few seconds.

**Test it from anywhere (e.g. your own computer's browser):**
Open `http://YOUR_DROPLET_IP/` in a browser (use the IP you copied in Part 1).
You should see `{"service":"vmedical-agent","status":"running"}`.

---

## Part 5 — Everyday commands (bookmark these)

Run these in the droplet console whenever you need them:

| I want to...                        | Type this                                  |
|-------------------------------------|--------------------------------------------|
| See if the agent is running         | `systemctl status vmedical-agent`          |
| Watch live logs (Ctrl+C to stop)    | `journalctl -u vmedical-agent -f`          |
| Restart the agent                   | `systemctl restart vmedical-agent`         |
| Stop the agent                      | `systemctl stop vmedical-agent`            |
| Start the agent                     | `systemctl start vmedical-agent`           |
| Change settings (key, model, etc.)  | `nano /opt/vmedical-agent/.env`            |

After changing anything in `.env`, always run
`systemctl restart vmedical-agent`.

---

## Part 6 — When you update the code

If you (or I) make changes to the project on GitHub, pull them onto the droplet
like this:

```bash
cd ~/vmedical-agent
git pull
bash deploy/setup.sh
```

The setup script safely updates everything and **keeps your `.env`** (your key
stays put). It restarts the service for you.

---

## Optional — Add a domain name and a padlock (HTTPS)

Using the raw IP address (`http://164.92.xx.xx`) works, but if you want a proper
address like `https://agent.yoursite.com` with the secure padlock, do this
**after** everything above is working:

1. In your domain registrar (GoDaddy, Namecheap, etc.), add an **A record**
   pointing your chosen subdomain (e.g. `agent`) to your droplet's IP address.
   Wait ~15 minutes for it to take effect.
2. On the droplet, tell nginx your domain name:
   ```bash
   nano /etc/nginx/sites-available/vmedical-agent
   ```
   Change `server_name _;` to `server_name agent.yoursite.com;` (use your real
   domain). Save (Ctrl+O, Enter, Ctrl+X).
3. Turn on free HTTPS with Certbot:
   ```bash
   apt-get install -y certbot python3-certbot-nginx
   certbot --nginx -d agent.yoursite.com
   ```
   Answer the prompts (enter your email, agree to terms, choose to redirect
   HTTP to HTTPS). Certbot sets everything up and auto-renews the certificate.

Your agent is now at `https://agent.yoursite.com`.

---

## Recommended — Turn on the firewall

For a bit of safety, allow only web and login traffic:

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
```

---

## Troubleshooting

- **"api_key_configured": false** → Your key isn't set. Run
  `nano /opt/vmedical-agent/.env`, paste the real key, save, then
  `systemctl restart vmedical-agent`.
- **Can't reach it from your browser** → Check the service is running
  (`systemctl status vmedical-agent`) and that you're using `http://` (not
  `https://`) with the correct IP.
- **"Model error" in the reply** → Usually a bad/expired API key or no billing
  set up on your Anthropic account. Check https://console.anthropic.com.
- **Something is badly broken** → A droplet is disposable. You can destroy it in
  the DigitalOcean panel and start this guide over on a fresh one. Nothing on
  your own computer is affected.

---

## What each file in this project is (for the curious)

| File                              | What it's for                                        |
|-----------------------------------|------------------------------------------------------|
| `app.py`                          | The agent web service itself.                        |
| `requirements.txt`                | The list of software the app needs.                  |
| `.env.example`                    | A template for your secret settings.                 |
| `deploy/setup.sh`                 | The one-command installer you ran in Part 3.         |
| `deploy/vmedical-agent.service`   | Tells Linux to run the app 24/7 and restart on crash.|
| `deploy/nginx.conf.example`       | The internet "front door" configuration.             |
| `test_key.py`                     | A tiny script to check your API key works.           |

You're all set. If you get stuck on any step, tell me which step number and what
you saw on screen, and I'll help you through it.
