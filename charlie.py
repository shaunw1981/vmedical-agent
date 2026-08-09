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


def _system_prompt(context: str) -> str:
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
        "You cannot send emails or texts yet; that capability is coming. If asked to "
        "send something, say you'll be able to once it's enabled.\n\n"
        "## KNOWLEDGE BASE (clinic notes)\n"
        f"{kb}"
    )


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

    messages: list[dict] = []
    for turn in (history or [])[-10:]:
        role = "assistant" if turn.get("role") == "charlie" else "user"
        content = (turn.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=config.CHARLIE_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_system_prompt(context),
            messages=messages,
        )
        answer = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Charlie couldn't answer: {exc}"}

    if not answer:
        return {"ok": False, "error": "Charlie returned an empty response — try rephrasing."}
    return {"ok": True, "answer": answer, "sources": [h["title"] for h in hits]}


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
