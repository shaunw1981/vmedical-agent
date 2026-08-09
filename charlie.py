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


def _system_prompt(context: str) -> str:
    name = config.CHARLIE_NAME
    kb = context or "(No matching notes were found in the knowledge base for this question.)"
    return (
        f"You are {name}, the AI assistant for the Valley Medical team dashboard. "
        "You help staff with the dashboard, client knowledge, appointments, and "
        "social media. Answer using the KNOWLEDGE BASE excerpts below (from the "
        "clinic's Obsidian notes) whenever they are relevant, and mention which "
        "note an answer came from. If the notes don't cover the question, answer "
        "from general knowledge and say plainly when you're unsure — do not invent "
        "client details. Keep answers concise and practical.\n\n"
        "You cannot send emails or texts yet; that capability is coming. If asked "
        "to send something, say you'll be able to once it's enabled.\n\n"
        "KNOWLEDGE BASE\n"
        "==============\n"
        f"{kb}"
    )


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
    hits = retrieve(sample_query)
    return {
        "charlie_enabled": enabled(),
        "model": config.CHARLIE_MODEL,
        "vault_configured": obsidian.is_configured(),
        "vault_base": str(base) if base else None,
        "sample_query": sample_query,
        "sample_hits": [h["title"] for h in hits],
    }
