"""
charlie.py — "Ask Charlie", the clinic's AI assistant.

Charlie answers the team's questions grounded in the Obsidian knowledge base
(call transcripts, client notes, and anything else filed in the vault). As the
vault grows, Charlie has more to draw on — so it gets more useful by the day.

How it works:
  1. Pull the notes most relevant to the question out of the vault (a light
     keyword search — no external index, no embedding cost).
  2. Hand those excerpts to Claude as grounding, along with the recent
     conversation, and return Charlie's answer.

Sending email/text is intentionally NOT wired up here yet — that's the next
phase, and it will require an explicit human "send" confirmation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import config
import obsidian

_PERSONA_FILE = Path(__file__).parent / "charlie_persona.md"

# Retrieval limits — keep it fast and keep the prompt affordable.
_MAX_FILES_SCANNED = 800
_MAX_FILE_CHARS = 20000
_TOP_K = 6
_SNIPPET_CHARS = 1500
_MAX_CONTEXT_CHARS = 12000
_MAX_TOKENS = 4000

_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_STOP = {"the", "and", "for", "with", "you", "your", "what", "when", "where", "how",
         "who", "why", "are", "was", "were", "this", "that", "have", "has", "can",
         "does", "did", "will", "about", "from", "our", "their", "them", "they"}


def enabled() -> bool:
    return config.charlie_enabled()


def _vault_base() -> Optional[Path]:
    if not obsidian.VAULT_PATH:
        return None
    base = Path(obsidian.VAULT_PATH) / obsidian.SUBFOLDER
    return base if base.exists() else None


def _terms(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall((text or "").lower()) if w not in _STOP]


def retrieve(query: str, k: int = _TOP_K) -> list[dict]:
    """Top-k vault notes for the question, scored by keyword frequency."""
    base = _vault_base()
    if not base:
        return []
    terms = set(_terms(query))
    if not terms:
        return []
    scored: list[tuple[float, dict]] = []
    for i, md in enumerate(base.rglob("*.md")):
        if i >= _MAX_FILES_SCANNED:
            break
        try:
            text = md.read_text(encoding="utf-8")[:_MAX_FILE_CHARS]
        except Exception:  # noqa: BLE001
            continue
        low = text.lower()
        name_low = md.name.lower()
        score = 0.0
        for t in terms:
            score += low.count(t)
            if t in name_low:
                score += 5  # filename matches weigh more
        if score > 0:
            scored.append((score, {"path": str(md), "title": md.stem, "text": text}))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [item for _score, item in scored[:k]]


def _best_snippet(text: str, query_terms: set[str]) -> str:
    """A window of the note around the first keyword hit."""
    low = text.lower()
    pos = min((low.find(t) for t in query_terms if low.find(t) >= 0), default=0)
    start = max(0, pos - 200)
    return text[start:start + _SNIPPET_CHARS].strip()


def _build_context(hits: list[dict], query: str) -> str:
    terms = set(_terms(query))
    blocks, total = [], 0
    for h in hits:
        snippet = _best_snippet(h["text"], terms)
        block = f"### Note: {h['title']}\n{snippet}"
        if total + len(block) > _MAX_CONTEXT_CHARS:
            break
        blocks.append(block)
        total += len(block)
    return "\n\n".join(blocks)


_DEFAULT_PERSONA = (
    "You are Charlie, the friendly, empathetic assistant for Valley Medical "
    "Aesthetics in Kentville, Nova Scotia. Warm, professional, and reassuring, "
    "with Maritime hospitality."
)


def _brain_dir() -> Optional[Path]:
    """Charlie's brain folder inside the Obsidian vault — the home of its knowledge."""
    base = _vault_base()
    return (base / "Charlie") if base else None


def _persona_path() -> Optional[Path]:
    d = _brain_dir()
    return (d / "Persona.md") if d else None


def _load_persona() -> str:
    """
    The editable personality, read fresh each turn so edits apply with no restart.
    Home is the Obsidian vault (Charlie/Persona.md); the repo file is a seed
    fallback; a short built-in default is the last resort.
    """
    p = _persona_path()
    if p and p.exists():
        try:
            text = p.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:  # noqa: BLE001
            pass
    try:
        text = _PERSONA_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    except Exception:  # noqa: BLE001
        pass
    return _DEFAULT_PERSONA


def _send_paragraph(can_email: bool, can_sms: bool) -> str:
    channels = []
    if can_email:
        channels.append("email (send_email)")
    if can_sms:
        channels.append("text/SMS (send_sms)")
    if not channels:
        return ("You cannot send emails or texts yet; that capability isn't switched on. "
                "If asked to send something, say it isn't enabled yet.")
    return (
        f"You can propose sending {' and '.join(channels)} — but ONLY when a team member "
        "explicitly asks you to send/email/text someone. Use the matching tool to draft "
        "the message in your warm Charlie voice. IMPORTANT: calling a send tool does NOT "
        "send anything — it creates a draft that a team member must review and approve "
        "first. Never claim you have sent a message; say you've drafted it for approval. "
        "Include the recipient if you know it from context or the notes; otherwise leave "
        "it blank and the team member will fill it in."
    )


def _system_prompt(context: str, can_email: bool = False, can_sms: bool = False) -> str:
    persona = _load_persona()
    kb = context or "(No matching notes were found in the knowledge base for this question.)"
    return (
        f"{persona}\n\n"
        "## Operating context (internal dashboard)\n"
        "You're speaking with Valley Medical **team members** inside their internal "
        "staff dashboard — not patients directly. Help them with client questions, "
        "appointments, the dashboard, and social media, and draft patient-facing "
        "messages in your Charlie voice when they ask. Greet warmly at the start of a "
        "conversation, but don't repeat a full greeting on every reply. Answer using "
        "the KNOWLEDGE BASE notes below (from the clinic's Obsidian vault) whenever "
        "they're relevant, and mention which note an answer came from. If the notes "
        "don't cover it, answer from what you know and say plainly when you're unsure "
        "— never invent client details.\n\n"
        f"{_send_paragraph(can_email, can_sms)}\n\n"
        "## KNOWLEDGE BASE (clinic notes)\n"
        f"{kb}"
    )


def _send_tools(can_email: bool, can_sms: bool) -> list[dict]:
    tools: list[dict] = []
    if can_email:
        tools.append({
            "name": "send_email",
            "description": (
                "Draft an email from the clinic's assistant mailbox for a team member to "
                "review and approve. Call ONLY when a team member explicitly asks you to "
                "email someone. Does NOT send — a human approves first."),
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address (blank if unknown)."},
                    "subject": {"type": "string", "description": "Email subject line."},
                    "body": {"type": "string", "description": "Email body in Charlie's warm voice."},
                },
                "required": ["body"],
            },
        })
    if can_sms:
        tools.append({
            "name": "send_sms",
            "description": (
                "Draft a text message (SMS) from the clinic's phone number for a team "
                "member to review and approve. Call ONLY when a team member explicitly "
                "asks you to text someone. Keep it short. Does NOT send — a human "
                "approves first."),
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient phone number (blank if unknown)."},
                    "body": {"type": "string", "description": "The text message (keep it concise)."},
                },
                "required": ["body"],
            },
        })
    return tools


_BRAIN_README = """# Charlie's Brain

This folder is Charlie's home. Everything Charlie knows about Valley Medical
lives here as plain Markdown notes — edit these in Obsidian and Charlie picks up
the changes on the next question (no restart needed).

- **Persona.md** — who Charlie is and how it speaks. Edit to tune personality.
- **Knowledge/** — what Charlie knows: services, pricing, policies, FAQs,
  post-care, booking. Add or edit notes here to teach Charlie. One topic per
  file works best.

Charlie also reads the rest of the vault (e.g. Clients/…), so client history
and call transcripts are already part of what it can draw on.
"""

_KN_SERVICES = """# Services & Treatments

## Vein Care
- **EVLT (EndoVenous Laser Treatment)** — for larger varicose veins.
- **Sclerotherapy** — injection treatment for spider/smaller veins.
- **Elos Laser** — for spider veins.

## Medical Aesthetics
- Laser skin rejuvenation
- Skin tightening (ReFirme / InMode)
- Rosacea, acne, and anti-aging treatments

## Products & Fittings
- Certified compression stocking fittings
- Sports / medical bracing
- Medical-grade skin care

<!-- Add detail per treatment: what it's for, what to expect, downtime, who it suits. -->
"""

_KN_PRICING = """# Pricing & Policies

<!-- Fill in so Charlie can answer accurately. Examples: -->
- Consultation fee (if any):
- Deposit / booking policy:
- Cancellation / no-show policy:
- Payment methods / financing:
- Insurance & compression-stocking coverage notes:
"""

_KN_FAQ = """# Frequently Asked Questions

<!-- One question per bullet, with the clinic's answer. Charlie will use these. -->
- **Is there downtime?** Most non-surgical procedures have minimal to no downtime.
- **Are treatments doctor-performed?** Treatments are doctor-performed or
  doctor-supervised, led by vascular expertise.
- **How do I book?**
- **Do you treat spider veins and varicose veins?**
"""

_KN_POSTCARE = """# Post-Care Instructions

<!-- Add per-treatment aftercare so Charlie can guide patients and staff. -->
## EVLT
## Sclerotherapy
## Laser / skin treatments
## Compression fittings
"""

_KN_CONTACT = """# Booking & Contact

- **Location:** 81 Exhibition St, Centennial Professional Centre, Kentville, NS B4N 1C2
- **Phone:** (902) 678-2121
- **Toll-Free:** 1-888-471-8346
- **Email:** hello@vmedical.ca
- **Website:** https://vmedical.ca

Encourage patients to book a consultation, call, or email to discuss their needs.
"""


def setup_brain() -> dict:
    """
    Create Charlie's brain folder structure in the Obsidian vault, seeding
    starter notes. Never overwrites files that already exist — safe to re-run.
    """
    base = _vault_base()
    if not base:
        return {"ok": False, "error": "Obsidian vault isn't set up yet "
                                      "(set OBSIDIAN_VAULT_PATH and restart)."}
    brain = base / "Charlie"
    knowledge = brain / "Knowledge"
    try:
        knowledge.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Couldn't create the brain folder: {exc}"}

    created, existed = [], []

    def seed(path: Path, content: str) -> None:
        if path.exists():
            existed.append(path.name)
        else:
            path.write_text(content, encoding="utf-8")
            created.append(path.name)

    try:
        persona_seed = _PERSONA_FILE.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        persona_seed = _DEFAULT_PERSONA
    seed(brain / "Persona.md", persona_seed)
    seed(brain / "README.md", _BRAIN_README)
    seed(knowledge / "Services.md", _KN_SERVICES)
    seed(knowledge / "Pricing & Policies.md", _KN_PRICING)
    seed(knowledge / "FAQ.md", _KN_FAQ)
    seed(knowledge / "Post-Care Instructions.md", _KN_POSTCARE)
    seed(knowledge / "Booking & Contact.md", _KN_CONTACT)

    return {"ok": True, "brain": str(brain), "created": created, "existed": existed}


def ask(question: str, history: Optional[list[dict]] = None) -> dict:
    """
    Answer a question. `history` is prior turns [{role:'user'|'charlie', content}].
    Returns {"ok": bool, "answer"|"error": str, "sources": [titles]}.
    """
    question = (question or "").strip()
    if not question:
        return {"ok": False, "error": "Ask Charlie a question first."}
    if not enabled():
        return {"ok": False, "error": "Charlie isn't connected yet (set ANTHROPIC_API_KEY)."}

    try:
        import anthropic
    except ImportError:
        return {"ok": False, "error": "The 'anthropic' package isn't installed — run update.command."}

    hits = retrieve(question)
    context = _build_context(hits, question)
    can_email = config.email_send_enabled()
    can_sms = config.ghl_contacts_enabled()
    tools = _send_tools(can_email, can_sms)

    messages: list[dict] = []
    for turn in (history or [])[-10:]:
        role = "assistant" if turn.get("role") == "charlie" else "user"
        content = (turn.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        kwargs = dict(
            model=config.CHARLIE_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_system_prompt(context, can_email, can_sms),
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools
        resp = client.messages.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Charlie couldn't answer: {exc}"}

    answer_parts, action = [], None
    for b in resp.content:
        btype = getattr(b, "type", None)
        if btype == "text":
            answer_parts.append(b.text)
        elif btype == "tool_use" and action is None and getattr(b, "name", "") in ("send_email", "send_sms"):
            inp = getattr(b, "input", None) or {}
            if b.name == "send_email":
                action = {"channel": "email", "to": (inp.get("to") or "").strip(),
                          "subject": (inp.get("subject") or "").strip(),
                          "body": (inp.get("body") or "").strip()}
            else:
                action = {"channel": "sms", "to": (inp.get("to") or "").strip(),
                          "subject": "", "body": (inp.get("body") or "").strip()}
    answer = "".join(answer_parts).strip()

    if action and not action["body"]:
        action = None  # empty draft — ignore
    if action and not answer:
        kind = "text" if action["channel"] == "sms" else "email"
        who = f" to {action['to']}" if action["to"] else ""
        answer = (f"I've drafted a {kind}{who} — review it below and click "
                  "Approve to send, or edit it first.")
    if not answer and not action:
        return {"ok": False, "error": "Charlie returned an empty response — try rephrasing."}
    return {"ok": True, "answer": answer, "sources": [h["title"] for h in hits], "action": action}


def _converse_system(context: str, direction: Optional[str]) -> str:
    persona = _load_persona()
    kb = context or "(No matching notes were found in the knowledge base.)"
    direction_block = ""
    if direction:
        direction_block = (
            "\n## Team direction for this reply\n"
            "A Valley Medical team member has told you how to respond. Follow it, "
            "written in your warm Charlie voice:\n"
            f"\"{direction}\"\n"
        )
    return (
        f"{persona}\n\n"
        "## Operating context (texting a patient)\n"
        "You are replying to a **patient/contact of the clinic by SMS**, on the "
        "clinic's behalf. Keep replies warm, brief, and text-message appropriate. "
        "Use the KNOWLEDGE BASE below when relevant. \n\n"
        "SAFETY — this matters: never give specific medical advice, diagnoses, "
        "dosing, or clinical guidance; never make firm commitments about pricing, "
        "insurance, or specific appointment times/availability unless the knowledge "
        "base clearly supports it. If you do NOT have enough information to answer "
        "confidently and safely — or the person needs a human, is upset, or is "
        "asking something clinical — do NOT guess. Call escalate_to_team with the "
        "exact question you need answered. Otherwise call reply_to_contact with the "
        "message to send. Always call exactly one of the two tools.\n"
        f"{direction_block}\n"
        "## KNOWLEDGE BASE (clinic notes)\n"
        f"{kb}"
    )


_CONVERSE_TOOLS = [
    {
        "name": "reply_to_contact",
        "description": ("Send-ready reply to the patient by SMS, in Charlie's warm voice. "
                        "Use only when you can answer confidently and safely."),
        "input_schema": {
            "type": "object",
            "properties": {"message": {"type": "string",
                           "description": "The SMS reply to the patient (concise)."}},
            "required": ["message"],
        },
    },
    {
        "name": "escalate_to_team",
        "description": ("Hand off to a Valley Medical team member because you can't answer "
                        "confidently/safely. Provide the specific question you need clarity on."),
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string",
                           "description": "What you need the team to clarify."}},
            "required": ["question"],
        },
    },
]


def converse(contact_name: Optional[str], history: list[dict], latest_text: str,
             direction: Optional[str] = None) -> dict:
    """
    Decide how to respond to a patient's text. `history` is prior turns
    [{role:'contact'|'charlie'|'team', body}]. Returns one of:
      {"ok": True, "action": "reply", "message": str, "sources": [...]}
      {"ok": True, "action": "handoff", "question": str, "sources": [...]}
      {"ok": False, "error": str}
    On any failure the caller should hand off to the team so nothing is dropped.
    """
    latest_text = (latest_text or "").strip()
    if not enabled():
        return {"ok": False, "error": "Charlie isn't connected (set ANTHROPIC_API_KEY)."}
    try:
        import anthropic
    except ImportError:
        return {"ok": False, "error": "The 'anthropic' package isn't installed."}

    query = direction or latest_text
    hits = retrieve(query)
    context = _build_context(hits, query)

    messages: list[dict] = []
    for turn in (history or [])[-12:]:
        role = "assistant" if turn.get("role") == "charlie" else "user"
        body = (turn.get("body") or "").strip()
        if not body:
            continue
        # Label who said non-Charlie lines so the model keeps the thread straight.
        if turn.get("role") == "team":
            body = f"[team member] {body}"
        messages.append({"role": role, "content": body})
    if latest_text and (not messages or messages[-1]["role"] != "user"):
        messages.append({"role": "user", "content": latest_text})
    if not messages:
        messages.append({"role": "user", "content": latest_text or "(no message)"})

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=config.CHARLIE_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_converse_system(context, direction),
            messages=messages,
            tools=_CONVERSE_TOOLS,
            tool_choice={"type": "any"},
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Charlie couldn't draft a reply: {exc}"}

    sources = [h["title"] for h in hits]
    text_parts = []
    for b in resp.content:
        if getattr(b, "type", None) == "tool_use":
            inp = getattr(b, "input", None) or {}
            if b.name == "reply_to_contact":
                msg = (inp.get("message") or "").strip()
                if msg:
                    return {"ok": True, "action": "reply", "message": msg, "sources": sources}
            elif b.name == "escalate_to_team":
                q = (inp.get("question") or "").strip()
                return {"ok": True, "action": "handoff",
                        "question": q or "Charlie wasn't sure how to answer this.",
                        "sources": sources}
        elif getattr(b, "type", None) == "text":
            text_parts.append(b.text)
    # No usable tool call — treat plain text as a draft if present, else hand off.
    draft = "".join(text_parts).strip()
    if draft:
        return {"ok": True, "action": "reply", "message": draft, "sources": sources}
    return {"ok": True, "action": "handoff",
            "question": "Charlie wasn't sure how to answer this.", "sources": sources}


def debug(sample_query: str = "test") -> dict:
    """Diagnostic for /charlie?debug=1 (no secrets)."""
    base = _vault_base()
    brain = _brain_dir()
    persona = _persona_path()
    hits = retrieve(sample_query)
    if persona and persona.exists():
        persona_source = "obsidian"
    elif _PERSONA_FILE.exists():
        persona_source = "repo-seed"
    else:
        persona_source = "default"
    return {
        "charlie_enabled": enabled(),
        "model": config.CHARLIE_MODEL,
        "vault_configured": obsidian.is_configured(),
        "vault_base": str(base) if base else None,
        "brain_dir": str(brain) if brain else None,
        "brain_exists": bool(brain and brain.exists()),
        "persona_source": persona_source,
        "sample_query": sample_query,
        "sample_hits": [h["title"] for h in hits],
    }


def brain_ready() -> bool:
    d = _brain_dir()
    return bool(d and d.exists())
