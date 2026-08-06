# vmedical-agent

An always-on web service that answers medical-information questions using Claude.

- **Non-developer?** Start here → **[SETUP.md](SETUP.md)** — a plain-English,
  step-by-step guide to putting this on a DigitalOcean droplet.
- It exposes three endpoints: `GET /` (status), `GET /health` (health check),
  and `POST /chat` (send `{"message": "..."}`, get `{"reply": "..."}`).

> ⚠️ This provides general information only — it is not a doctor and must not be
> used with real patient data on a basic droplet. See the cautions in SETUP.md.

## Run it locally (for testing on your own computer)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env and add your ANTHROPIC_API_KEY
uvicorn app:app --reload
```

Then open http://127.0.0.1:8000/ in your browser.
