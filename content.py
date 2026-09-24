"""
content.py — the blog Content workspace: draft with Charlie, preview, and push
to WordPress in Valley Medical's house style.

The house style is a FIXED template: the CSS below (scoped to `.vma-calf-blog`)
and a brand header. Each post is only the article HTML that uses these classes,
so every post looks like the client's approved design. We store the article
markup per post; the CSS lives here once. On push we wrap it into the exact
single `<!-- wp:html -->` block the client pasted into WordPress.

Building blocks (classes Charlie must use):
  <article class="vma-calf-blog"> … </article>          the whole post
    .intro   → .label (eyebrow) + <h1> (may use <em> for a colour accent) + p.dek
    figure.hero → <img> + <figcaption>                  lead image
    .benefits  → 3 × (<div><strong>word</strong><span>line</span></div>)
    .article   → narrow reading column wrapping <section>s
      p.lead, <h2>, <p>, .pull (a pull-quote div)
    section.split → figure + text block (label + h2 + p)  full-width feature
    ol.steps   → numbered <li> (use <strong> to lead each)
    section.attention → a safety/when-to-seek-care callout
    .closing-panel → .label + h2 + p + p.closing         the CTA close
"""

from __future__ import annotations

import re
from typing import Optional

import charlie
import config

# --- The fixed house-style CSS (scoped to .vma-calf-blog / .vma-calf-brand) ---
BLOG_CSS = """.vma-calf-blog{--navy:#1d406f;--teal:#265360;--ink:#283440;--pale:#eef3f4;color:var(--ink);font:19px/1.75 Georgia,serif;max-width:1120px;margin:auto}.vma-calf-blog *{box-sizing:border-box}.vma-calf-blog h1{font-size:64px;line-height:1.06;font-weight:normal;letter-spacing:-2px;color:var(--navy);margin:15px 0 22px}.vma-calf-blog h1 em{font-style:normal;color:var(--teal)}.vma-calf-blog h2{font-size:32px;line-height:1.2;font-weight:normal;color:var(--teal);margin:0 0 20px}.vma-calf-blog p{margin:0 0 22px}.vma-calf-blog .label{font:600 11px/1.6 Arial,sans-serif;text-transform:uppercase;letter-spacing:2.1px;color:var(--teal)}.vma-calf-blog .intro{padding:50px 36px 34px;max-width:900px}.vma-calf-blog .dek{font-size:23px;line-height:1.5;color:#586f80;max-width:690px}.vma-calf-blog figure{margin:0}.vma-calf-blog img{display:block;width:100%;height:auto}.vma-calf-blog .hero img{aspect-ratio:2.2;object-fit:cover;object-position:50% 53%}.vma-calf-blog figcaption{font:12px/1.5 Arial,sans-serif;color:#617786;padding:12px 0}.vma-calf-blog .hero figcaption{padding:12px 36px}.vma-calf-blog .benefits{background:var(--navy);color:white;display:grid;grid-template-columns:repeat(3,1fr);padding:27px 36px;gap:30px;margin:10px 36px 46px}.vma-calf-blog .benefits strong{font-size:24px;font-weight:normal;display:block}.vma-calf-blog .benefits span{font:14px/1.5 Arial,sans-serif;color:#e1e9f0;display:block;margin-top:5px}.vma-calf-blog .article{max-width:760px;margin:0 auto;padding:0 24px}.vma-calf-blog section{margin-bottom:38px}.vma-calf-blog .lead{font-size:23px;color:var(--teal)}.vma-calf-blog .pull{border-left:3px solid #a6bec6;padding-left:24px;font-size:29px;line-height:1.4;color:var(--teal);margin:32px 0}.vma-calf-blog .split{margin:48px 36px;display:grid;grid-template-columns:1.1fr 1fr;align-items:center;background:var(--pale);gap:32px;padding:26px}.vma-calf-blog .split p{font-size:18px}.vma-calf-blog .split p:last-child{margin:0}.vma-calf-blog .steps{padding:0;list-style:none;counter-reset:steps}.vma-calf-blog .steps li{counter-increment:steps;padding:16px 0 16px 48px;position:relative;border-bottom:1px solid #d8e1e6}.vma-calf-blog .steps li:before{content:counter(steps,decimal-leading-zero);position:absolute;left:0;color:var(--teal);font:600 15px/2 Arial,sans-serif}.vma-calf-blog .attention{background:#f3f5f7;border-top:3px solid var(--navy);padding:26px;font-size:16px}.vma-calf-blog .attention h2{font-size:25px}.vma-calf-blog .attention p:last-child{margin:0}.vma-calf-blog .closing{font-size:23px;color:var(--teal)}.vma-calf-blog .sources{font:12px/1.7 Arial,sans-serif;border-top:1px solid #d8e1e6;padding:22px 0 32px;color:#617786}.vma-calf-blog a{color:var(--teal);text-underline-offset:3px}@media(max-width:760px){.vma-calf-blog .intro{padding:32px 22px 20px}.vma-calf-blog h1{font-size:46px}.vma-calf-blog .dek{font-size:21px}.vma-calf-blog .hero img{aspect-ratio:1.4;object-position:67% 50%}.vma-calf-blog .hero figcaption{padding:12px 22px}.vma-calf-blog .benefits{grid-template-columns:1fr;margin:10px 22px 34px;gap:20px;padding:25px}.vma-calf-blog .split{grid-template-columns:1fr;margin:35px 22px;padding:20px;gap:15px}.vma-calf-blog h2{font-size:29px}.vma-calf-blog .pull{font-size:26px}}
.vma-calf-blog .closing-panel{background:var(--pale);padding:32px;margin:42px 0}.vma-calf-blog .closing-panel p:last-child{margin-bottom:0}.vma-calf-blog .closing-panel .label{margin-bottom:14px}.vma-calf-blog .hero img{aspect-ratio:1.95;object-position:50% 52%}.vma-calf-blog .split img{aspect-ratio:1.25;object-fit:cover;object-position:52% 50%}.vma-calf-blog .sources{display:none}@media(max-width:760px){.vma-calf-blog h1{font-size:42px;letter-spacing:-1.2px}.vma-calf-blog .hero img{aspect-ratio:1.4;object-position:60% 50%}.vma-calf-blog .closing-panel{padding:24px}.vma-calf-blog{font-size:18px}}
.vma-calf-brand{max-width:1048px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;padding:26px 0;border-bottom:1px solid #d8e1e6;font:11px/1.7 Arial,sans-serif;color:#617786;letter-spacing:1px}.vma-calf-brand img{width:310px;max-width:100%;height:auto}.vma-calf-brand span{margin-left:20px}@media(max-width:760px){.vma-calf-brand{margin:0 22px}.vma-calf-brand img{width:250px}.vma-calf-brand span{display:none}}"""

_DEFAULT_LOGO = "images/valley-medical-logo.png"


def _brand_header() -> str:
    logo = config.WORDPRESS_LOGO_URL or _DEFAULT_LOGO
    return (f'<div class="vma-calf-brand"><img src="{logo}" '
            'alt="Valley Medical — Veins Skin Move">'
            '<span>LEG HEALTH<br>EVERYDAY WELLBEING</span></div>')


def render_preview(title: str, body_html: str) -> str:
    """A standalone HTML document (brand + article + CSS) for the editor iframe."""
    safe_title = (title or "Preview").replace("<", "").replace(">", "")
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{safe_title}</title><style>body{{margin:0;background:#fff}}\n"
        + BLOG_CSS + "\n</style></head><body>"
        + _brand_header() + "\n" + (body_html or "") + "</body></html>"
    )


def render_for_wordpress(body_html: str) -> str:
    """The exact single `<!-- wp:html -->` block to store as the WordPress post."""
    return (
        "<!-- wp:html -->\n<style>\n" + BLOG_CSS + "\n</style>\n"
        + _brand_header() + "\n" + (body_html or "").strip() + "\n<!-- /wp:html -->"
    )


# --- Charlie content generation ----------------------------------------------
_TEMPLATE_CONTRACT = """You are writing a patient-education article for Valley Medical, a vein and medical
aesthetics clinic in Kentville, Nova Scotia and Summerside, PEI. Vein procedures
are performed by a vascular surgeon.

Output ONLY one HTML block: <article class="vma-calf-blog"> … </article>. No
markdown, no code fences, no <style>, no <html>/<head>, no commentary, no logo
bar — just the <article>. Use ONLY these building blocks and class names, in this
order (everything except the intro is optional):

<article class="vma-calf-blog">
  <div class="intro"><div class="label">Two-part kicker · like this</div><h1>A headline of six to ten words<br><em>broken onto a second line.</em></h1><p class="dek">One-sentence deck that frames the piece.</p></div>
  <figure class="hero"><img src="https://cms.vmedical.ca/wp-content/uploads/REPLACE-hero.jpg" alt="Describe the image"><figcaption>A one-sentence caption that adds something the picture does not say.</figcaption></figure>
  <div class="benefits"><div><strong>Word</strong><span>One short sentence.</span></div><div><strong>Word</strong><span>One short sentence.</span></div><div><strong>Word</strong><span>One short sentence.</span></div></div>
  <div class="article">
    <p class="lead">An opening lead paragraph, larger and teal.</p>
    <section><h2>A section heading</h2><p>…</p><div class="pull">A short pull-quote line.<br>A second line.</div></section>
    <section><h2>Another section</h2><p>…</p></section>
  </div>
  <section class="split"><figure><img src="https://cms.vmedical.ca/wp-content/uploads/REPLACE-feature.jpg" alt="Describe"><figcaption>Caption.</figcaption></figure><div><div class="label">SMALL LABEL</div><h2>A feature<br>call-out.</h2><p>…</p></div></section>
  <div class="article">
    <section><h2>A checklist section</h2><ol class="steps"><li><strong>Do this.</strong> One sentence of detail.</li></ol></section>
  </div>
  <section class="attention"><h2>When to seek care</h2><p>Plain safety guidance…</p></section>
  <div class="closing-panel"><div class="label">Your next step</div><h2>A gentle<br>closing line.</h2><p>Invite the reader to Valley Medical…</p><p class="closing">A warm final sentence.</p></div>
</article>

Notes on the blocks:
- <em> in the h1 is NOT italic; it colours the second line teal. Exactly one <h1> (in .intro).
- .benefits has exactly three items. .steps has four to six items, each led by a bolded instruction.
- .split closes the reading column and a new <div class="article"> reopens it after.

Rules (follow strictly):
- Every image src is an absolute https://cms.vmedical.ca/wp-content/uploads/… URL with descriptive alt text. If you do not have a real uploaded image, use https://cms.vmedical.ca/wp-content/uploads/REPLACE-hero.jpg (or REPLACE-feature.jpg) as a placeholder for the team to swap. NEVER use a relative path, and never invent a real-looking URL.
- No logo bar, no second <h1>, no inline style="" attributes.
- Canadian spelling. Do NOT use em dashes anywhere: use commas, colons or full stops.
- Write "Dr" with no full stop.
- Plain, calm, specific. Explain the mechanism before the advice.
- Say what a treatment does and does not do. Never promise an outcome.
- Frame anything clinical as "ask your clinician" rather than direction.
- Aim for 700 to 1100 words in total. Do not invent prices, statistics, or
  clinic-specific claims that are not in the knowledge base."""


def _content_system(context: str) -> str:
    persona = charlie._load_persona()
    kb = context or "(No specific clinic notes were found for this topic; write from general, careful knowledge.)"
    return (
        f"{persona}\n\n"
        f"{_TEMPLATE_CONTRACT}\n\n"
        "## KNOWLEDGE BASE (clinic notes to ground the post)\n"
        f"{kb}"
    )


_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_STYLE_RE = re.compile(r"(?is)<style.*?</style>")


def _clean_article(text: str) -> str:
    """Strip code fences / stray <style>, and ensure a single <article> wrapper."""
    t = (text or "").strip()
    t = _FENCE_RE.sub("", t).strip()
    t = _STYLE_RE.sub("", t).strip()
    # Keep from the first <article to the last </article> if present.
    lo = t.lower()
    start = lo.find("<article")
    end = lo.rfind("</article>")
    if start != -1 and end != -1:
        return t[start:end + len("</article>")]
    # Model returned inner content only — wrap it.
    if t:
        return '<article class="vma-calf-blog">\n' + t + '\n</article>'
    return ""


def slugify(text: str) -> str:
    """Lowercase, hyphenated, no dates — matches the site's /blog/<slug>.html."""
    t = (text or "").strip().lower()
    t = re.sub(r"[’'\"]", "", t)
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:80] or "post"


def review(body: str) -> list[str]:
    """
    Warnings to show before publishing live, per the site's format doc:
    unreplaced/relative images and em dashes (the house style forbids them).
    """
    warnings: list[str] = []
    body = body or ""
    srcs = re.findall(r'<img[^>]+src="([^"]*)"', body, flags=re.I)
    if any("REPLACE" in s for s in srcs):
        warnings.append("Some images are still placeholders (REPLACE-…) — swap in real "
                        "https://cms.vmedical.ca/wp-content/uploads/… URLs first.")
    if any(not s.lower().startswith("https://") for s in srcs):
        warnings.append("Some image paths aren't absolute https URLs — the site can't fetch "
                        "relative paths and they'll 404 on the live site.")
    if "—" in body or "–" in body:
        warnings.append("The draft contains an em/en dash — the house style uses commas, "
                        "colons or full stops instead.")
    if body.lower().count("<h1") > 1:
        warnings.append("There's more than one <h1> — the layout allows only the intro headline.")
    return warnings


def generate(brief: str, title: Optional[str] = None,
             existing: Optional[str] = None, provider: Optional[str] = None) -> dict:
    """
    Draft (or refine) a post body in the house style from a brief. Returns
    {"ok": bool, "body"|"error": str, "sources": [titles]}.
    """
    brief = (brief or "").strip()
    if not brief and not existing:
        return {"ok": False, "error": "Give Charlie a topic or brief first."}
    if not config.charlie_enabled():
        return {"ok": False, "error": "Charlie isn't connected "
                "(set CHARLIE_PROVIDER=ollama, or add an ANTHROPIC_API_KEY)."}

    hits = charlie.retrieve(brief or (title or ""))
    context = charlie._build_context(hits, brief or (title or ""))

    parts = []
    if title:
        parts.append(f"Working title: {title}")
    parts.append(f"Brief / topic:\n{brief}" if brief else "Improve the draft below.")
    if existing:
        parts.append("Here is the current draft to revise (keep what works, "
                     "improve clarity and structure, keep the same house style):\n"
                     + existing)
    user = "\n\n".join(parts)

    try:
        text = charlie.chat_once(_content_system(context), user, provider)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Charlie couldn't draft this: {exc}"}

    body = _clean_article(text)
    if not body:
        return {"ok": False, "error": "Charlie returned an empty draft — try rephrasing the brief."}
    return {"ok": True, "body": body, "sources": [h["title"] for h in hits]}
