"""
photos.py — local storage + image processing for patient progress photos.

EVERYTHING stays on the Mac. Nothing is uploaded anywhere. For each patient we
create a folder under PHOTOS_PATH and, per position, store:
  • the original capture (EXIF-rotated so it's upright),
  • a standardized crop to the position's aspect ratio (consistent framing),
  • a small thumbnail.

We also compute a lightweight "framing score" — how closely a new shot lines up
with the previous shot of the same position — as a heuristic nudge for the team.
It is NOT medical analysis and no image ever leaves the machine.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageChops, ImageOps, ImageStat

import config

_STD_LONG_EDGE = 1600   # px, long edge of the standardized image
_THUMB_W = 480          # px, thumbnail width


def root() -> Path:
    p = Path(config.photos_path())
    p.mkdir(parents=True, exist_ok=True)
    return p


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "x"


def patient_folder_name(patient: dict) -> str:
    last = _slug(patient.get("last_name") or "")
    first = _slug(patient.get("first_name") or "")
    name = "-".join([p for p in (last, first) if p]) or "patient"
    return f"{int(patient['id']):05d}-{name}"


def abs_path(rel: str) -> Path:
    """Resolve a stored relative path against the current photo root (safely)."""
    base = root().resolve()
    target = (base / rel).resolve()
    if base not in target.parents and target != base:
        raise ValueError("path escapes the photo store")
    return target


def _cover_crop(img: Image.Image, aspect_w: int, aspect_h: int) -> Image.Image:
    """Center-crop `img` to the target aspect ratio (no distortion)."""
    target = aspect_w / aspect_h
    w, h = img.size
    cur = w / h
    if cur > target:          # too wide → trim sides
        new_w = int(round(h * target))
        x0 = (w - new_w) // 2
        box = (x0, 0, x0 + new_w, h)
    else:                     # too tall → trim top/bottom
        new_h = int(round(w / target))
        y0 = (h - new_h) // 2
        box = (0, y0, w, y0 + new_h)
    return img.crop(box)


def _framing_score(prev_std_abs: Optional[Path], std_img: Image.Image) -> tuple[Optional[int], str]:
    """Rough 0-100 similarity to the previous same-position standardized photo."""
    if not prev_std_abs or not prev_std_abs.exists():
        return None, "First photo for this position — it becomes the reference."
    try:
        a = ImageOps.grayscale(Image.open(prev_std_abs)).resize((64, 64))
        b = ImageOps.grayscale(std_img).resize((64, 64))
        diff = ImageChops.difference(a, b)
        mean = ImageStat.Stat(diff).mean[0]      # 0 (identical) .. 255 (opposite)
        score = max(0, min(100, round((1 - mean / 255.0) * 100)))
    except Exception:  # noqa: BLE001
        return None, ""
    if score >= 85:
        note = "Framing looks consistent with the last photo."
    elif score >= 70:
        note = "Framing is slightly different from the last photo."
    else:
        note = "Framing differs noticeably — consider lining up with the ghost overlay and retaking."
    return score, note


def store(patient: dict, position: dict, image_bytes: bytes, taken_by: str = "",
          prev_std_rel: Optional[str] = None) -> dict:
    """
    Process and save one photo. Returns a metadata dict with RELATIVE paths
    (relative to the photo root) plus dimensions and a framing score.
    """
    aspect_w = int(position.get("aspect_w") or 3)
    aspect_h = int(position.get("aspect_h") or 4)
    pos_slug = position.get("slug") or _slug(position.get("name") or "position")

    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)           # honour phone orientation
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Standardized crop to the position ratio.
    std = _cover_crop(img, aspect_w, aspect_h)
    std.thumbnail((_STD_LONG_EDGE, _STD_LONG_EDGE), Image.LANCZOS)
    w, h = std.size

    thumb = std.copy()
    thumb.thumbnail((_THUMB_W, _THUMB_W * aspect_h // aspect_w), Image.LANCZOS)

    # Folder: <patient>/<position>/<timestamp>
    folder_rel = f"{patient_folder_name(patient)}/{pos_slug}"
    folder_abs = root() / folder_rel
    folder_abs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    orig_rel = f"{folder_rel}/{stamp}-orig.jpg"
    std_rel = f"{folder_rel}/{stamp}.jpg"
    thumb_rel = f"{folder_rel}/{stamp}-thumb.jpg"

    rgb = img.convert("RGB")
    rgb.save(root() / orig_rel, "JPEG", quality=92)
    std.convert("RGB").save(root() / std_rel, "JPEG", quality=90)
    thumb.convert("RGB").save(root() / thumb_rel, "JPEG", quality=82)

    prev_abs = abs_path(prev_std_rel) if prev_std_rel else None
    score, note = _framing_score(prev_abs, std)

    return {
        "orig_path": orig_rel, "std_path": std_rel, "thumb_path": thumb_rel,
        "width": w, "height": h, "framing_score": score, "framing_note": note,
    }


def delete_files(*rel_paths: Optional[str]) -> None:
    for rel in rel_paths:
        if not rel:
            continue
        try:
            p = abs_path(rel)
            if p.exists():
                p.unlink()
        except Exception:  # noqa: BLE001
            pass
