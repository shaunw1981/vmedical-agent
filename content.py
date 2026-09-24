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
import db

# --- The fixed house-style CSS (scoped to .vma-calf-blog / .vma-calf-brand) ---
# Re-skinned to the site's approved olive/cream palette (site.css tokens) and its
# Newsreader (headings) + Figtree (body) type. The layout structure is unchanged.
BLOG_CSS = """@import url('https://fonts.googleapis.com/css2?family=Figtree:wght@300;400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,200..600;1,6..72,300..500&display=swap');
.vma-calf-blog{--ink:#2A2B27;--deep:#5E6B51;--accent:#7D8B6E;--band:#2A2B27;--pale:#F3EEE7;--tint:#E7EAE1;--line:#E2DED6;--serif:"Newsreader",Georgia,"Times New Roman",serif;--body:"Figtree","Helvetica Neue",Arial,sans-serif;color:var(--ink);font:400 18px/1.7 var(--body);max-width:1120px;margin:auto}
.vma-calf-blog *{box-sizing:border-box}
.vma-calf-blog h1{font-family:var(--serif);font-size:60px;line-height:1.06;font-weight:400;letter-spacing:-1.4px;color:var(--ink);margin:15px 0 22px}
.vma-calf-blog h1 em{font-style:normal;color:var(--accent)}
.vma-calf-blog h2{font-family:var(--serif);font-size:32px;line-height:1.2;font-weight:400;color:var(--deep);margin:0 0 20px}
.vma-calf-blog p{margin:0 0 22px}
.vma-calf-blog .label{font:600 11px/1.6 var(--body);text-transform:uppercase;letter-spacing:2.1px;color:var(--deep)}
.vma-calf-blog .intro{padding:50px 36px 34px;max-width:900px}
.vma-calf-blog .dek{font-family:var(--serif);font-style:italic;font-size:24px;line-height:1.5;color:#5E6157;max-width:690px}
.vma-calf-blog figure{margin:0}
.vma-calf-blog img{display:block;width:100%;height:auto}
.vma-calf-blog .hero img{aspect-ratio:1.95;object-fit:cover;object-position:50% 52%}
.vma-calf-blog figcaption{font:12px/1.5 var(--body);color:#5E6157;padding:12px 0}
.vma-calf-blog .hero figcaption{padding:12px 36px}
.vma-calf-blog .benefits{background:var(--band);color:#fff;display:grid;grid-template-columns:repeat(3,1fr);padding:27px 36px;gap:30px;margin:10px 36px 46px}
.vma-calf-blog .benefits strong{font-family:var(--serif);font-size:24px;font-weight:400;display:block}
.vma-calf-blog .benefits span{font:14px/1.5 var(--body);color:var(--tint);display:block;margin-top:5px}
.vma-calf-blog .article{max-width:760px;margin:0 auto;padding:0 24px}
.vma-calf-blog section{margin-bottom:38px}
.vma-calf-blog .lead{font-family:var(--serif);font-style:italic;font-size:23px;color:var(--deep)}
.vma-calf-blog .pull{border-left:3px solid #C4CDB6;padding-left:24px;font-family:var(--serif);font-style:italic;font-size:29px;line-height:1.4;color:var(--deep);margin:32px 0}
.vma-calf-blog .split{margin:48px 36px;display:grid;grid-template-columns:1.1fr 1fr;align-items:center;background:var(--pale);gap:32px;padding:26px}
.vma-calf-blog .split img{aspect-ratio:1.25;object-fit:cover;object-position:52% 50%}
.vma-calf-blog .split p{font-size:18px}
.vma-calf-blog .split p:last-child{margin:0}
.vma-calf-blog .steps{padding:0;list-style:none;counter-reset:steps}
.vma-calf-blog .steps li{counter-increment:steps;padding:16px 0 16px 48px;position:relative;border-bottom:1px solid var(--line)}
.vma-calf-blog .steps li:before{content:counter(steps,decimal-leading-zero);position:absolute;left:0;color:var(--deep);font:600 15px/2 var(--body)}
.vma-calf-blog .attention{background:var(--pale);border-top:3px solid var(--band);padding:26px;font-size:16px}
.vma-calf-blog .attention h2{font-size:25px}
.vma-calf-blog .attention p:last-child{margin:0}
.vma-calf-blog .closing-panel{background:var(--pale);padding:32px;margin:42px 0}
.vma-calf-blog .closing-panel p:last-child{margin-bottom:0}
.vma-calf-blog .closing-panel .label{margin-bottom:14px}
.vma-calf-blog .closing{font-family:var(--serif);font-style:italic;font-size:23px;color:var(--deep)}
.vma-calf-blog .sources{display:none}
.vma-calf-blog a{color:var(--deep);text-underline-offset:3px}
.vma-calf-blog .vma-suggest{display:flex;align-items:center;justify-content:center;text-align:center;background:var(--tint);border:1.5px dashed #9fae90;color:#5E6B51;font-family:var(--body);font-size:.92rem;line-height:1.5;padding:24px}
.vma-calf-blog .hero.vma-suggest{aspect-ratio:1.95}
.vma-calf-blog .split .vma-suggest{aspect-ratio:1.25}
.vma-calf-blog .vma-suggest::before{content:"Suggested photo: " attr(data-suggest)}
@media(max-width:760px){.vma-calf-blog .intro{padding:32px 22px 20px}.vma-calf-blog h1{font-size:40px;letter-spacing:-1px}.vma-calf-blog .dek{font-size:21px}.vma-calf-blog .hero img{aspect-ratio:1.4;object-position:60% 50%}.vma-calf-blog .hero figcaption{padding:12px 22px}.vma-calf-blog .benefits{grid-template-columns:1fr;margin:10px 22px 34px;gap:20px;padding:25px}.vma-calf-blog .split{grid-template-columns:1fr;margin:35px 22px;padding:20px;gap:15px}.vma-calf-blog h2{font-size:28px}.vma-calf-blog .pull{font-size:26px}.vma-calf-blog{font-size:17px}}
.vma-calf-brand{max-width:1048px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;padding:26px 0;border-bottom:1px solid #E2DED6;font:11px/1.7 "Figtree","Helvetica Neue",Arial,sans-serif;color:#5E6157;letter-spacing:1px}.vma-calf-brand img{width:310px;max-width:100%;height:auto}.vma-calf-brand span{margin-left:20px}@media(max-width:760px){.vma-calf-brand{margin:0 22px}.vma-calf-brand img{width:250px}.vma-calf-brand span{display:none}}"""

_DEFAULT_LOGO = "images/valley-medical-logo.png"


def _brand_header() -> str:
    logo = (config.WORDPRESS_LOGO_URL or "").strip()
    if logo:
        mark = f'<img src="{logo}" alt="Valley Medical — Veins Skin Move">'
    else:
        # No logo URL configured — show a text wordmark instead of a broken image.
        # (The site build strips this brand bar anyway; it's only a preview aid.)
        mark = ('<strong style="font-family:\'Newsreader\',Georgia,serif;font-size:23px;'
                'font-weight:500;letter-spacing:.02em;color:#2A2B27">Valley Medical</strong>')
    return (f'<div class="vma-calf-brand">{mark}'
            '<span>LEG HEALTH<br>EVERYDAY WELLBEING</span></div>')


def render_preview(title: str, body_html: str) -> str:
    """A standalone HTML document (brand + article + CSS) for the editor iframe."""
    safe_title = (title or "Preview").replace("<", "").replace(">", "")
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{safe_title}</title><style>\n"
        + BLOG_CSS + "\nbody{margin:0;background:#fff}\n</style></head><body>"
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
  <figure class="hero vma-suggest" data-suggest="a short plain description of the ideal hero photo"><figcaption>A one-sentence caption that adds something the picture does not say.</figcaption></figure>
  <div class="benefits"><div><strong>Word</strong><span>One short sentence.</span></div><div><strong>Word</strong><span>One short sentence.</span></div><div><strong>Word</strong><span>One short sentence.</span></div></div>
  <div class="article">
    <p class="lead">An opening lead paragraph, larger and teal.</p>
    <section><h2>A section heading</h2><p>…</p><div class="pull">A short pull-quote line.<br>A second line.</div></section>
    <section><h2>Another section</h2><p>…</p></section>
  </div>
  <section class="split"><figure class="vma-suggest" data-suggest="a short description of the feature photo"><figcaption>Caption.</figcaption></figure><div><div class="label">SMALL LABEL</div><h2>A feature<br>call-out.</h2><p>…</p></div></section>
  <div class="article">
    <section><h2>A checklist section</h2><ol class="steps"><li><strong>Do this.</strong> One sentence of detail.</li></ol></section>
  </div>
  <section class="attention"><h2>When to seek care</h2><p>Plain safety guidance…</p></section>
  <div class="closing-panel"><div class="label">Your next step</div><h2>A gentle<br>closing line.</h2><p>Invite the reader to Valley Medical…</p><p class="closing">A warm final sentence.</p></div>
</article>

Notes on the blocks:
- <em> in the h1 is NOT italic; it sets the second line in the brand accent colour. Exactly one <h1> (in .intro).
- .benefits has exactly three items. .steps has four to six items, each led by a bolded instruction.
- .split closes the reading column and a new <div class="article"> reopens it after.

Rules (follow strictly):
- Do NOT insert any <img> tags or image URLs. Where a photo belongs, output an EMPTY placeholder figure that DESCRIBES the ideal photo, and the team adds the real image later:
    Hero: <figure class="hero vma-suggest" data-suggest="short plain description of the ideal photo, no quotes"><figcaption>…</figcaption></figure>
    In a split/section: <figure class="vma-suggest" data-suggest="short description"><figcaption>…</figcaption></figure>
  Keep data-suggest to a short plain-text description (no quotation marks, no HTML). Use one hero and, at most, one or two more.
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


def extract_title(body: str) -> str:
    """The headline text from the article's <h1> (joining its two lines)."""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", body or "", flags=re.I | re.S)
    if not m:
        return ""
    inner = re.sub(r"(?i)<br\s*/?>", " ", m.group(1))
    text = re.sub(r"<[^>]+>", "", inner)
    return re.sub(r"\s+", " ", text).strip()


def image_suggestions(body: str) -> list[dict]:
    """The photo ideas Charlie left in the article (from data-suggest placeholders)."""
    out = []
    for d in re.findall(r'data-suggest="([^"]*)"', body or "", flags=re.I):
        d = d.strip()
        if d:
            out.append({"desc": d})
    return out


def review(body: str) -> list[str]:
    """Warnings to show before publishing live."""
    warnings: list[str] = []
    body = body or ""
    if "vma-suggest" in body:
        warnings.append("Some photo spots are still empty suggestions — add the images "
                        "before publishing, or they'll show as placeholder boxes.")
    srcs = re.findall(r'<img[^>]+src="([^"]*)"', body, flags=re.I)
    if any(not s.lower().startswith("https://") for s in srcs):
        warnings.append("Some image paths aren't absolute https URLs — the site can't fetch "
                        "relative paths and they'll 404 on the live site.")
    if "—" in body or "–" in body:
        warnings.append("The draft contains an em/en dash — the house style uses commas, "
                        "colons or full stops instead.")
    if body.lower().count("<h1") > 1:
        warnings.append("There's more than one <h1> — the layout allows only the intro headline.")
    return warnings


def _engine_unavailable(provider: str) -> Optional[str]:
    """A friendly error if the resolved content engine can't run, else None."""
    if provider == "anthropic" and not config.ANTHROPIC_API_KEY:
        return ("Content is set to draft with Anthropic (CHARLIE_CONTENT_PROVIDER=anthropic) "
                "but no ANTHROPIC_API_KEY is set. Add the key, or set CHARLIE_CONTENT_PROVIDER=ollama.")
    if provider != "anthropic" and not config.charlie_enabled() and provider != "ollama":
        return "Charlie isn't connected (set CHARLIE_PROVIDER, or add an ANTHROPIC_API_KEY)."
    return None


def generate(brief: str, title: Optional[str] = None,
             existing: Optional[str] = None, provider: Optional[str] = None,
             exclude_id: Optional[int] = None) -> dict:
    """
    Draft (or refine) a post body in the house style from a brief. Returns
    {"ok": bool, "body"|"error": str, "sources": [titles]}.
    """
    brief = (brief or "").strip()
    if not brief and not existing:
        return {"ok": False, "error": "Give Charlie a topic or brief first."}
    prov = provider or config.charlie_provider_for("content")
    err = _engine_unavailable(prov)
    if err:
        return {"ok": False, "error": err}

    hits = charlie.retrieve(brief or (title or ""))
    context = charlie._build_context(hits, brief or (title or ""))
    exemplar, recent_titles = _learning_context(brief or (title or ""), exclude_id)

    parts = []
    if title:
        parts.append(f"Working title: {title}")
    parts.append(f"Brief / topic:\n{brief}" if brief else "Improve the draft below.")
    if existing:
        parts.append("Here is the current draft to revise (keep what works, "
                     "improve clarity and structure, keep the same house style):\n"
                     + existing)
    if exemplar:
        parts.append("Here is one of Valley Medical's own PUBLISHED posts. Match its voice, "
                     "rhythm and structure, but write a completely fresh piece — do not copy "
                     "its wording or topic:\n" + exemplar)
    if recent_titles:
        parts.append("Recently published (do NOT repeat these topics): "
                     + "; ".join(recent_titles))
    user = "\n\n".join(parts)

    try:
        text = charlie.chat_once(_content_system(context), user, prov,
                                 model=config.charlie_model_for("content"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Charlie couldn't draft this: {exc}"}

    body = _clean_article(text)
    if not body:
        return {"ok": False, "error": "Charlie returned an empty draft — try rephrasing the brief."}
    learned = len(recent_titles)
    return {"ok": True, "body": body, "sources": [h["title"] for h in hits],
            "learned_from": learned, "title": extract_title(body)}


def _learning_context(query: str, exclude_id: Optional[int] = None) -> tuple[str, list[str]]:
    """
    Charlie's 'always learning' corpus: the most relevant previously published
    post as a voice exemplar, plus recent titles to avoid repeating topics.
    """
    posts = [p for p in db.list_published_posts(20)
             if p.get("id") != exclude_id and (p.get("body") or "").strip()]
    if not posts:
        return "", []
    terms = set(charlie._terms(query or ""))

    def score(p: dict) -> int:
        hay = f"{p.get('title','')} {p.get('brief','')} {p.get('excerpt','')}".lower()
        return sum(hay.count(t) for t in terms)

    best = max(posts, key=score) if terms else posts[0]
    exemplar = (best.get("body") or "")[:2800]
    titles = [p.get("title") for p in posts[:8] if p.get("title")]
    return exemplar, titles


# --- AI image placement ------------------------------------------------------
_PLACE_SYSTEM = """You are editing an existing Valley Medical blog article written in the fixed house
style (the outer element is <article class="vma-calf-blog">). You will be given the
article and one image to add. Return the FULL updated article and nothing else.

Placement rules:
- If the article has empty placeholder figures (class contains "vma-suggest", with a
  data-suggest description), REPLACE the single most relevant one with a real figure,
  removing the vma-suggest class and the data-suggest attribute:
    <figure class="hero"><img src="URL" alt="ALT"><figcaption>keep or improve the caption</figcaption></figure>
  (use class "hero" if the placeholder was the hero; otherwise a plain <figure>).
- If there are no placeholders, add it where it best supports the nearby text: a
  <figure><img src="URL" alt="ALT"><figcaption>…</figcaption></figure> inside the most
  relevant <section>, or as a <section class="split"> feature.
- Use the exact image URL and alt text given. Write a short, specific <figcaption>.
- Do NOT change, add or remove any of the article's existing words. Only swap the image
  in. Return ONLY the <article>…</article>, no markdown, no commentary."""


def place_image(body: str, image_url: str, alt: str,
                note: Optional[str] = None, provider: Optional[str] = None) -> dict:
    """Ask Charlie to insert an uploaded image at the best spot. Returns {ok, body|error}."""
    if not (body or "").strip():
        return {"ok": False, "error": "Write the draft first, then add images."}
    prov = provider or config.charlie_provider_for("content")
    err = _engine_unavailable(prov)
    if err:
        return {"ok": False, "error": err}
    user = (f"Image URL: {image_url}\nAlt text: {alt or '(none given)'}\n"
            + (f"Note about the image: {note}\n" if note else "")
            + "\nArticle to edit:\n" + body)
    try:
        text = charlie.chat_once(_PLACE_SYSTEM, user, prov,
                                 model=config.charlie_model_for("content"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Charlie couldn't place the image: {exc}"}
    new_body = _clean_article(text)
    if not new_body or image_url not in new_body:
        return {"ok": False, "error": "Charlie didn't return a usable placement — "
                "you can paste the image into the body manually."}
    return {"ok": True, "body": new_body}


def image_in_hero(body: str, image_url: str) -> bool:
    """True if the image URL sits inside the <figure class="hero"> block."""
    m = re.search(r"<figure[^>]*class=['\"][^'\"]*hero[^'\"]*['\"][^>]*>.*?</figure>",
                  body or "", flags=re.I | re.S)
    return bool(m and image_url in m.group(0))
