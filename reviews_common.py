"""
reviews_common.py — shared aggregation for the Reviews page.

Both the GoHighLevel and the Google Business sources produce a list of
"normalized" review dicts (rating, reviewer, text, source, date, replied,
reply, …). This turns that list into the single overview shape the
reviews.html template renders, so the page looks identical whatever the source.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def aggregate(normalized: list[dict], now: datetime, sampled: bool = False) -> dict:
    reviews = sorted(normalized, key=lambda r: r.get("_sort") or datetime.min, reverse=True)
    rated = [r for r in reviews if r.get("rating", 0) > 0]
    count = len(reviews)
    average = round(sum(r["rating"] for r in rated) / len(rated), 1) if rated else 0.0

    distribution = {s: 0 for s in (5, 4, 3, 2, 1)}
    for r in rated:
        distribution[r["rating"]] += 1

    sources: dict[str, int] = {}
    for r in reviews:
        sources[r["source"]] = sources.get(r["source"], 0) + 1

    unreplied = sum(1 for r in reviews if not r.get("replied"))
    since = now - timedelta(days=30)
    recent_30 = sum(1 for r in reviews if (r.get("_sort") or datetime.min) >= since)

    return {
        "totals": {
            "count": count,
            "average": average,
            "average_rounded": int(round(average)),
            "rated": len(rated),
            "unreplied": unreplied,
            "replied": count - unreplied,
            "sources": sources,
            "distribution": distribution,
            "recent_30": recent_30,
        },
        "recent": reviews[:12],
        "sampled": sampled,
        "generated_at": now.strftime("%b %-d, %Y at %-I:%M %p UTC"),
    }
