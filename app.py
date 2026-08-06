"""
vmedical-agent — always-on web service.

This is a small web server. It sits on your DigitalOcean droplet and waits
for messages. When someone sends a message to the /chat endpoint, it asks
Claude to respond and sends the answer back.

You normally do NOT run this file by hand on the server. The setup turns it
into a background service that starts automatically and restarts if it ever
crashes. See SETUP.md for the full walkthrough.
"""

import os

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Load settings (like your API key) from the .env file that lives next to this
# file. Keeping secrets in .env means they never get committed to GitHub.
load_dotenv()

# Which Claude model to use. You can change this in your .env file without
# touching the code — just add a line like: MODEL=claude-sonnet-5
MODEL = os.environ.get("MODEL", "claude-sonnet-5")

# The "personality" and rules for the agent. Edit this text to change how the
# agent behaves. This one is written as a cautious medical-information helper.
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    (
        "You are vMedical Agent, a careful and friendly medical-information "
        "assistant. You provide general health information and help people "
        "understand their questions. You are NOT a doctor and do NOT diagnose, "
        "prescribe, or replace professional medical care. Always remind users "
        "to consult a qualified healthcare professional for personal medical "
        "advice, and tell them to call emergency services for emergencies."
    ),
)

# Create the Anthropic client once, when the server starts. It reads the key
# from the ANTHROPIC_API_KEY value in your .env file.
_api_key = os.environ.get("ANTHROPIC_API_KEY")
client = Anthropic(api_key=_api_key) if _api_key else None

app = FastAPI(title="vmedical-agent", version="1.0.0")


class ChatRequest(BaseModel):
    """The shape of a message coming in to /chat."""

    message: str


class ChatResponse(BaseModel):
    """The shape of the answer we send back."""

    reply: str


@app.get("/")
def home():
    """A friendly landing message so you can confirm the service is alive."""
    return {"service": "vmedical-agent", "status": "running"}


@app.get("/health")
def health():
    """
    A simple health check. Monitoring tools (and you) can hit this to confirm
    the service is up and that the API key is configured.
    """
    return {"status": "ok", "api_key_configured": client is not None}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    Send a message to the agent and get a reply.

    Example of how another program would call this:
        POST /chat   with body   {"message": "What is a fever?"}
        returns              {"reply": "A fever is..."}
    """
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY is not set. Add it to the .env file.",
        )

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty.")

    try:
        result = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": request.message}],
        )
        reply_text = result.content[0].text
    except Exception as exc:  # noqa: BLE001 - surface a clean error to callers
        raise HTTPException(status_code=502, detail=f"Model error: {exc}") from exc

    return ChatResponse(reply=reply_text)
