# Valley Medical — Receptionist Agent

The first of Valley Medical's automated agents. It receives **call transcripts by
email** from the GoHighLevel (GHL) Virtual Voice Agent, understands what the caller
needed, and takes the appropriate action back in GHL.

## Flow

```
Caller ──▶ GHL Virtual Voice Agent ──▶ emails transcript ──▶ assistant@vmedical.ca
                                                                     │
                                                                     ▼
                                                       Receptionist Agent (this repo)
                                                       1. Ingest the transcript email
                                                       2. Understand the call (Claude)
                                                       3. Act in GHL (contact, appt,
                                                          message-taking, notify staff)
```

- **Agent inbox:** `assistant@vmedical.ca` (dedicated Google Workspace mailbox)
- **Back end of record:** GoHighLevel (Valley Medical location)

## Build plan (incremental)

| Step | Scope | Status |
|------|-------|--------|
| 1 | Foundation: project structure, config, secrets, thin GHL client | ✅ done |
| 2a | Inbox connection: Gmail API + read-only OAuth ingestion | ✅ done |
| 2b | Transcript parsing (needs a real sample email) | ⏳ next |
| 3 | Understanding: Claude classifies the call + extracts details | ⬜ |
| 4 | Action: map intents → GHL operations | ⬜ |
| 5 | Wire end-to-end + deploy | ⬜ |

We intentionally build the transcript parser and action logic **after** seeing a
real sample email, so the structure matches what GHL actually sends.

## Layout

```
receptionist/
  config.py         # env-based settings
  ghl_client.py     # thin GoHighLevel API v2 client
  gmail_client.py   # read-only Gmail ingestion for the agent inbox
authorize_gmail.py  # one-time OAuth consent → writes token.json
fetch_sample.py     # prints the newest inbox email (connection test / sample grab)
.env.example        # template — copy to .env and fill in
```

## Connecting the agent inbox (Gmail API + OAuth)

The agent reads `assistant@vmedical.ca` with a **read-only** Gmail OAuth
credential. One-time setup:

**A. In Google Cloud Console** (signed in as / with access to the vmedical.ca
Workspace):

1. Create a project (e.g. "Valley Medical Agents").
2. **APIs & Services → Library →** enable the **Gmail API**.
3. **OAuth consent screen:** User type **Internal** (keeps it inside the
   vmedical.ca Workspace — no Google verification needed). Add your email as a
   test user if prompted.
4. **Credentials → Create credentials → OAuth client ID →** application type
   **Desktop app**. Download the JSON and save it as `credentials.json` in the
   repo root.

**B. Authorize the mailbox** (once, on a machine with a browser, signed in as
`assistant@vmedical.ca`):

```bash
pip install -r requirements.txt
python authorize_gmail.py     # opens a browser → consent → writes token.json
```

**C. Verify the connection** (after a test call has landed a transcript):

```bash
python fetch_sample.py        # prints the newest email in the inbox
```

`credentials.json` and `token.json` are gitignored — they hold OAuth secrets and
must never be committed.

## Configuration

Copy `.env.example` to `.env` and fill in values. `.env` is gitignored; never commit
real secrets.

- `ANTHROPIC_API_KEY` — Claude API
- `GHL_LOCATION_ID`, `GHL_PRIVATE_TOKEN` — GoHighLevel (Valley Medical location)

## Notes / open items

- **GHL egress:** the GHL API host is blocked by the build sandbox's network policy,
  so live GHL calls are verified where the agent is deployed, not from the build
  environment.
- **Runtime/hosting:** not yet decided — how the agent runs day-to-day (polling the
  inbox vs. webhook-triggered) is settled in a later step.
- **Behavior:** what the agent does per call type is defined once we have a sample
  transcript.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in
```
