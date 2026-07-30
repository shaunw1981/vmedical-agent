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
| 2 | Ingestion: read + parse transcript emails (needs a real sample) | ⏳ next |
| 3 | Understanding: Claude classifies the call + extracts details | ⬜ |
| 4 | Action: map intents → GHL operations | ⬜ |
| 5 | Wire end-to-end + deploy | ⬜ |

We intentionally build the transcript parser and action logic **after** seeing a
real sample email, so the structure matches what GHL actually sends.

## Layout

```
receptionist/
  config.py       # env-based settings
  ghl_client.py   # thin GoHighLevel API v2 client
.env.example      # template — copy to .env and fill in
```

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
