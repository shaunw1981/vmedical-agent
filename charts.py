"""
charts.py — dependency-free inline-SVG chart geometry.

Pure functions that turn numbers into SVG coordinates, so templates can draw
bars / lines / donuts with plain <rect>, <polyline> and <circle> — no chart
library, no JavaScript, nothing to download (which keeps the PWA working
offline). The scaling / polyline / donut-dash math lives here (not in Jinja)
so it stays readable and unit-testable.

Each function returns a plain dict the matching macro in templates/_macros.html
renders directly.
"""

from __future__ import annotations

import math
from typing import Optional


def bar_series(values: list[float], labels: Optional[list[str]] = None,
               width: int = 560, height: int = 150, gap: int = 10,
               pad_top: int = 8, pad_bottom: int = 20) -> dict:
    """Vertical bars scaled to the largest value."""
    n = len(values)
    labels = labels or [""] * n
    vmax = max(values) if values and max(values) > 0 else 1
    inner_h = height - pad_top - pad_bottom
    slot = width / n if n else width
    bw = max(4.0, slot - gap)
    baseline = pad_top + inner_h
    bars = []
    for i, v in enumerate(values):
        h = (v / vmax) * inner_h
        x = i * slot + (slot - bw) / 2
        y = baseline - h
        bars.append({
            "x": round(x, 1), "y": round(y, 1), "w": round(bw, 1),
            "h": round(h, 1), "cx": round(x + bw / 2, 1),
            "value": v, "label": labels[i] if i < len(labels) else "",
        })
    return {"width": width, "height": height, "baseline": round(baseline, 1),
            "max": vmax, "bars": bars}


def line_series(values: list[float], width: int = 560, height: int = 150,
                pad: int = 10, pad_bottom: int = 20) -> dict:
    """A line + filled area from a numeric series."""
    n = len(values)
    vmax = max(values) if values and max(values) > 0 else 1
    inner_h = height - pad - pad_bottom
    step = (width - 2 * pad) / (n - 1) if n > 1 else 0
    baseline = pad + inner_h
    pts = []
    for i, v in enumerate(values):
        x = pad + i * step
        y = pad + (inner_h - (v / vmax) * inner_h)
        pts.append((round(x, 1), round(y, 1), v))
    points = " ".join(f"{x},{y}" for x, y, _ in pts)
    if pts:
        area = (f"M {pts[0][0]},{round(baseline,1)} "
                + " ".join(f"L {x},{y}" for x, y, _ in pts)
                + f" L {pts[-1][0]},{round(baseline,1)} Z")
    else:
        area = ""
    return {"width": width, "height": height, "max": vmax, "points": points,
            "area": area, "dots": [{"x": x, "y": y, "value": v} for x, y, v in pts]}


def donut_segments(pairs: list[tuple], size: int = 160, stroke: int = 24) -> dict:
    """
    A donut from (label, value, color) tuples using stroke-dasharray on a
    <circle> (no arc-path trig). The macro rotates the group -90° so segments
    start at 12 o'clock.
    """
    r = (size - stroke) / 2
    cx = cy = size / 2
    circ = 2 * math.pi * r
    values_sum = sum(max(0, v) for _, v, _ in pairs)
    total = values_sum or 1
    segments = []
    acc = 0.0
    for label, value, color in pairs:
        frac = max(0, value) / total
        dash = frac * circ
        segments.append({
            "label": label, "value": value, "color": color,
            "pct": round(frac * 100),
            "dasharray": f"{round(dash, 2)} {round(circ - dash, 2)}",
            "dashoffset": round(-acc, 2),
        })
        acc += dash
    return {"size": size, "r": round(r, 2), "cx": cx, "cy": cy, "stroke": stroke,
            "circumference": round(circ, 2), "segments": segments, "total": values_sum}
