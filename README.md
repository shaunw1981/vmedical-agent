# vmedical-agent

A small, **local** notes app for a med spa. It runs on a **Mac Mini** at the
spa, captures **voicemail** and **appointment** notes from **GoHighLevel**, and
files each one into the client's **Obsidian vault** — the shared "brain" the
agents read from and write to. Everything is stored locally on the Mac.

- **Non-developer? Start here → [SETUP-MACMINI.md](SETUP-MACMINI.md)** — a
  plain-English, step-by-step setup guide.

## How it fits together

```
GoHighLevel  ─▶  vmedical-agent (Mac Mini)  ─▶  Obsidian vault  ─▶  Staff read
(voicemails,     writes each note as a           (Markdown files,      in Obsidian
 appointments)   Markdown file locally            the "brain")
```

## What's in here

| File                     | What it's for                                             |
|--------------------------|-----------------------------------------------------------|
| `app.py`                 | The notes app (receives notes, shows a viewer page).      |
| `obsidian.py`            | Writes notes into the Obsidian vault; searches history.   |
| `notes_db.py`            | Keeps a local database copy as a backup/log.              |
| `ghl_sync.py`            | Starter for pulling notes from GoHighLevel.               |
| `macmini/install.command`| Double-click installer for the Mac Mini.                  |
| `macmini/start.sh`       | Starts the app (kept running automatically).              |
| `SETUP-MACMINI.md`       | The full non-developer setup guide.                       |
| `.env.example`           | Settings template (vault path, options).                  |

## Privacy

Notes are stored **only on the Mac** (Obsidian vault + a local database file).
Nothing goes to the cloud unless you deliberately turn on the optional AI
tidy-up (`AI_CLEANUP=on`), which sends voicemail text to Anthropic to clean it
up. It is **off by default**. Med-spa client info is personal information under
Canadian privacy law (PIPEDA) — keep the Mac secured and access limited.

## Run it on your own computer to try it (optional)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # set OBSIDIAN_VAULT_PATH to a test folder
uvicorn app:app --reload    # then open http://127.0.0.1:8000
```
