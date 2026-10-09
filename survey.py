"""
survey.py — the Patient Satisfaction Survey definition, validation, and the math
that compiles responses for the dashboard.

Everything about the survey lives here in one place: the public form, the
submission validation, and the results aggregation all read this single
definition, so adding or re-wording a question only happens once.

The survey is ANONYMOUS by design — we never collect or store a name, email,
phone, or anything that identifies the patient. Only the answers are kept.
"""

from __future__ import annotations

from typing import Optional

# A stable key, so the storage can grow to hold more than one survey later.
SURVEY_KEY = "patient_satisfaction"

TITLE = "Patient Satisfaction Survey"
INTRO = ("Thank you for taking a moment to share your experience. This survey is "
         "completely anonymous — we don't ask for your name or any contact details.")

# Which procedure(s) the response relates to (optional for the patient).
TREATMENTS = ["Sclerotherapy", "EndoVenous Laser Treatment"]

# The 1–5 agreement scale used by the rated sections.
SCALE_MIN = 1
SCALE_MAX = 5
SCALE_MIN_LABEL = "Strongly disagree"
SCALE_MAX_LABEL = "Strongly agree"

# Question types:
#   likert  → a 1–5 agreement rating
#   yesno   → Yes / No
#   text    → a free-text answer (textarea)
# Each question has a stable `key` (used as the form field name and the stored
# answer key) and the human `text`.
SECTIONS = [
    {
        "title": "Scheduling your appointment",
        "type": "likert",
        "questions": [
            {"key": "sched_phone_prompt",   "text": "Your phone calls were answered promptly"},
            {"key": "sched_phone_friendly", "text": "Your phone interactions were friendly and pleasant"},
            {"key": "sched_timely_consult", "text": "A timely and convenient consultation appointment with a vein specialist was given"},
        ],
    },
    {
        "title": "Your appointment",
        "type": "likert",
        "questions": [
            {"key": "appt_wait_20",           "text": "Your wait time was less than 20 mins to see the surgeon"},
            {"key": "appt_staff_professional","text": "Staff was professional and courteous"},
            {"key": "appt_surgeon_listened",  "text": "The Surgeon listened to all of your concerns"},
            {"key": "appt_questions_answered","text": "All of your questions were answered"},
            {"key": "appt_tests_explained",   "text": "All of your tests and treatment options were explained to you"},
            {"key": "appt_reading_material",  "text": "Appropriate reading material was supplied for you to take home detailing what to expect during your procedure and afterwards"},
        ],
    },
    {
        "title": "The procedure",
        "type": "likert",
        "questions": [
            {"key": "proc_as_expected",  "text": "The procedure was performed as you expected from handouts and information from your initial consultation"},
            {"key": "proc_at_ease",      "text": "The staff and Surgeon did their best to put you at ease both before and during your procedure"},
            {"key": "proc_minimal_pain", "text": "There was minimal pain and discomfort"},
        ],
    },
    {
        "title": "A few more questions",
        "type": "mixed",
        "questions": [
            {"key": "ops_visited_site",   "type": "yesno", "text": "Have you previously visited our website?"},
            {"key": "ops_knew_site_info", "type": "yesno", "text": "Did you know that our website contains useful information about the services we provide, as well as maintaining the health of your veins?"},
            {"key": "ops_additional",     "type": "yesno", "text": "Are there any additional services or information that we can provide to you?",
             "explain": "If yes, please tell us what"},
            {"key": "ops_refer_friend",   "type": "yesno", "text": "Would you refer a friend to Valley Medical Aesthetics for services?"},
            {"key": "ops_wished_known",   "type": "yesno", "text": "Is there any information you wish you'd known before the procedure?",
             "explain": "If yes, what would have helped?"},
            {"key": "ops_willing_speak",  "type": "yesno", "text": "Would you be willing to speak to someone considering this procedure about your experience?"},
            {"key": "ops_met_expectations", "type": "text", "text": "Did the clinic meet or exceed your expectations? Anything else you'd like us to know?"},
        ],
    },
]


# --- Convenience accessors ---------------------------------------------------
def _questions_of(qtype: str) -> list[dict]:
    out = []
    for section in SECTIONS:
        for q in section["questions"]:
            effective = q.get("type") or section["type"]
            if effective == qtype:
                out.append({**q, "section": section["title"]})
    return out


def likert_questions() -> list[dict]:
    return _questions_of("likert")


def yesno_questions() -> list[dict]:
    return _questions_of("yesno")


def text_questions() -> list[dict]:
    return _questions_of("text")


def question_text(key: str) -> str:
    for section in SECTIONS:
        for q in section["questions"]:
            if q["key"] == key:
                return q["text"]
    return key


def likert_keys() -> set[str]:
    return {q["key"] for q in likert_questions()}


# --- Validation of an incoming submission ------------------------------------
def clean_submission(form: dict) -> dict:
    """
    Turn a raw submitted form (a plain dict of field→value, plus a possible list
    of selected treatments under 'treatment') into a clean, stored-ready dict:

        {"treatment": [..], "answers": {key: value, ...}}

    - Likert answers are kept only when they are a whole number in range.
    - Yes/No answers are kept only when they are exactly 'yes' or 'no'.
    - Optional 'explain' text and free-text answers are trimmed and length-capped.
    Returns the cleaned dict. Raises ValueError if nothing meaningful was answered
    (so an empty/bot submission isn't stored).
    """
    answers: dict = {}

    # Likert 1–5
    for q in likert_questions():
        raw = (form.get(q["key"]) or "").strip()
        if not raw:
            continue
        try:
            val = int(raw)
        except ValueError:
            continue
        if SCALE_MIN <= val <= SCALE_MAX:
            answers[q["key"]] = val

    # Yes / No (+ optional explain)
    for q in yesno_questions():
        raw = (form.get(q["key"]) or "").strip().lower()
        if raw in ("yes", "no"):
            answers[q["key"]] = raw
        if q.get("explain"):
            ex = (form.get(q["key"] + "_explain") or "").strip()
            if ex:
                answers[q["key"] + "_explain"] = ex[:1000]

    # Free text
    for q in text_questions():
        raw = (form.get(q["key"]) or "").strip()
        if raw:
            answers[q["key"]] = raw[:2000]

    # Treatment(s) — accept a single string or a list.
    raw_treat = form.get("treatment")
    if isinstance(raw_treat, str):
        raw_treat = [raw_treat]
    treatment = [t for t in (raw_treat or []) if t in TREATMENTS]

    if not answers:
        raise ValueError("No answers were provided.")

    return {"treatment": treatment, "answers": answers}


# --- Aggregation for the results dashboard -----------------------------------
def summarize(responses: list[dict]) -> dict:
    """
    Compile a list of stored responses (each a dict with 'answers' already parsed
    into a dict, and 'treatment' a list) into display-ready numbers.
    """
    total = len(responses)

    # Per-question Likert averages.
    likert_stats = []
    all_likert_values: list[int] = []
    section_values: dict[str, list[int]] = {}
    for q in likert_questions():
        vals = [r["answers"].get(q["key"]) for r in responses]
        vals = [v for v in vals if isinstance(v, int)]
        all_likert_values.extend(vals)
        section_values.setdefault(q["section"], []).extend(vals)
        avg = round(sum(vals) / len(vals), 2) if vals else None
        likert_stats.append({
            "key": q["key"], "text": q["text"], "section": q["section"],
            "avg": avg, "count": len(vals),
            "pct": round((avg - 1) / 4 * 100) if avg is not None else 0,  # 1→0%, 5→100%
        })

    section_stats = []
    for section in SECTIONS:
        if section["type"] != "likert":
            continue
        vals = section_values.get(section["title"], [])
        avg = round(sum(vals) / len(vals), 2) if vals else None
        section_stats.append({
            "title": section["title"], "avg": avg, "count": len(vals),
            "pct": round((avg - 1) / 4 * 100) if avg is not None else 0,
        })

    overall_avg = round(sum(all_likert_values) / len(all_likert_values), 2) if all_likert_values else None
    overall_pct = round((overall_avg - 1) / 4 * 100) if overall_avg is not None else 0

    # Yes/No breakdowns.
    yesno_stats = []
    for q in yesno_questions():
        yes = sum(1 for r in responses if r["answers"].get(q["key"]) == "yes")
        no = sum(1 for r in responses if r["answers"].get(q["key"]) == "no")
        answered = yes + no
        yesno_stats.append({
            "key": q["key"], "text": q["text"],
            "yes": yes, "no": no, "answered": answered,
            "yes_pct": round(yes / answered * 100) if answered else 0,
            "explain": q.get("explain"),
        })

    # "Would refer a friend" — the headline loyalty number.
    refer = next((y for y in yesno_stats if y["key"] == "ops_refer_friend"), None)

    # Free-text comments (newest first), incl. yes/no explain notes.
    comments = []
    for r in responses:
        a = r["answers"]
        bits = []
        for q in text_questions():
            if a.get(q["key"]):
                bits.append({"q": q["text"], "a": a[q["key"]]})
        for q in yesno_questions():
            if q.get("explain") and a.get(q["key"] + "_explain"):
                label = q["text"]
                bits.append({"q": label, "a": a[q["key"] + "_explain"]})
        if bits:
            comments.append({
                "created_at": r.get("created_at"),
                "treatment": r.get("treatment") or [],
                "entries": bits,
            })

    # Treatment mix.
    treatment_counts = {t: 0 for t in TREATMENTS}
    for r in responses:
        for t in (r.get("treatment") or []):
            if t in treatment_counts:
                treatment_counts[t] += 1

    return {
        "total": total,
        "overall_avg": overall_avg,
        "overall_pct": overall_pct,
        "section_stats": section_stats,
        "likert_stats": likert_stats,
        "yesno_stats": yesno_stats,
        "refer": refer,
        "comments": comments,
        "treatment_counts": treatment_counts,
    }
