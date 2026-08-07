#!/usr/bin/env python3
"""
make_icons.py — generate the PWA PNG icons for the dashboard.

Draws the sage "VM" mark (white stroke letters on a sage square) at the sizes a
PWA + iOS need, using ONLY the standard library (zlib/struct) — no Pillow, no
cairo, nothing to install. Run it whenever the mark changes:

    python3 scripts/make_icons.py

Outputs into static/icons/. The generated PNGs are committed to the repo so the
Mac never needs an imaging library at runtime.
"""

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "static" / "icons"
SAGE = (124, 138, 115)      # #7c8a73
WHITE = (255, 255, 255)


def _seg_dist(px, py, ax, ay, bx, by):
    """Distance from point (px,py) to segment a-b."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _wordmark_segments(size, margin):
    """Build the 'VM' stroke segments in canvas pixels for a square `size`."""
    lo = size * margin
    hi = size * (1 - margin)
    span = hi - lo
    top, bot = lo, hi
    gap = span * 0.08
    half = (span - gap) / 2
    # V in the left box, M in the right box.
    vx0, vx1 = lo, lo + half
    mx0, mx1 = hi - half, hi
    def lerp(a, b, t):
        return a + (b - a) * t
    V = [
        (lerp(vx0, vx1, 0.08), top), (lerp(vx0, vx1, 0.5), bot),
        (lerp(vx0, vx1, 0.5), bot), (lerp(vx0, vx1, 0.92), top),
    ]
    M = [
        (lerp(mx0, mx1, 0.06), bot), (lerp(mx0, mx1, 0.06), top),
        (lerp(mx0, mx1, 0.06), top), (lerp(mx0, mx1, 0.5), lerp(top, bot, 0.62)),
        (lerp(mx0, mx1, 0.5), lerp(top, bot, 0.62)), (lerp(mx0, mx1, 0.94), top),
        (lerp(mx0, mx1, 0.94), top), (lerp(mx0, mx1, 0.94), bot),
    ]
    pts = V + M
    return [(pts[i], pts[i + 1]) for i in range(0, len(pts), 2)], span


def _render(size, margin=0.20):
    """Return raw RGBA bytes for a `size`×`size` icon."""
    segs, span = _wordmark_segments(size, margin)
    stroke = span * 0.11
    half = stroke / 2
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter type 0 per scanline
        yc = y + 0.5
        for x in range(size):
            xc = x + 0.5
            d = min(_seg_dist(xc, yc, ax, ay, bx, by) for (ax, ay), (bx, by) in segs)
            cov = max(0.0, min(1.0, half - d + 0.75))  # cheap anti-aliasing
            r = round(SAGE[0] + (WHITE[0] - SAGE[0]) * cov)
            g = round(SAGE[1] + (WHITE[1] - SAGE[1]) * cov)
            b = round(SAGE[2] + (WHITE[2] - SAGE[2]) * cov)
            rows += bytes((r, g, b, 255))
    return bytes(rows)


def _write_png(path, size, raw):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # (filename, size, margin) — maskable uses a bigger margin (safe zone).
    targets = [
        ("icon-192.png", 192, 0.20),
        ("icon-512.png", 512, 0.20),
        ("icon-512-maskable.png", 512, 0.28),
        ("apple-touch-icon-180.png", 180, 0.20),
        ("favicon.png", 64, 0.16),
    ]
    for name, size, margin in targets:
        _write_png(OUT / name, size, _render(size, margin))
        print(f"wrote {name} ({size}px)")


if __name__ == "__main__":
    main()
