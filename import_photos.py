#!/usr/bin/env python3
"""
import_photos.py — review-first bulk importer for the clinic's existing photo
archive (the "CLIENT PHOTOS" folder copied onto this Mac).

It reads the archive's folder/file naming, turns each client folder into a
local patient record, and files every dated photo onto that patient through the
SAME pipeline the dashboard uses (EXIF-rotate → crop to the position's ratio →
thumbnail → framing score). Face shots become the patient's profile headshot.
EVERYTHING stays on this Mac; nothing is uploaded anywhere.

Expected archive layout (depth above the client folder doesn't matter):
    CLIENT PHOTOS / <service> / <letter> / <"Last, First <codes>"> / <files>
    file names:  "YYYY MM DD POSITION.jpg"   e.g.  "2023 03 10 A.jpg"

TWO STEPS — nothing is written until you run --commit:

  1) Scan (default). Discovers every position code with counts, every patient,
     and anything that doesn't parse. Writes an editable map template.
         python3 import_photos.py --scan

  2) Commit. Uses the (reviewed) map to create patients + import photos.
     Re-runnable: already-imported files are skipped (ledger), so you can do it
     in batches or resume after a stop.
         python3 import_photos.py --commit --map data/photo-import-map.json

Handy flags:  --only "Aalders"  (one patient, for a test)   --limit 5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Run from this script's own directory so the app's relative paths (DB_PATH,
# .env, data/) resolve to exactly what the live dashboard uses.
os.chdir(Path(__file__).resolve().parent)

import config          # noqa: E402  (after chdir so .env loads from here)
import db              # noqa: E402
import photos as photos_svc  # noqa: E402

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
OTHER_IMAGE_EXTS = {".heic", ".heif", ".tif", ".tiff", ".bmp", ".gif", ".webp"}

DEFAULT_ROOT = Path.home() / "Documents" / "CLIENT PHOTOS"
SCAN_FILE = Path("data/photo-import-scan.json")
MAP_FILE = Path("data/photo-import-map.json")
LEDGER_FILE = Path("data/photo-import-ledger.txt")

# Best-guess starting map (confirmed legs legend). Everything else → REVIEW.
# Base leg positions (confirmed legend). The normalizer rolls every messy
# filename variant back to one of these base letters; E/F/G/H… stay as-is and
# wait for the clinic's face/hand/neckline legend.
BASE_TO_SLUG = {
    "A": "legs-front",
    "B": "left-leg-side",
    "C": "right-leg-side",
    "D": "legs-back",
}

# Service / vein / housekeeping tokens that get appended to a position letter in
# filenames. Longest-first so "RGSVBAA" is stripped before "RGSV"/"BAA".
_CODE_SUFFIXES = ("RGSVBAA", "DRGSVBAA", "BEVLT", "RGSV", "LGSV", "BGSV", "GSV",
                  "EVLT", "UGF", "BAA", "EDITED", "COPY", "JPEG", "JPG", "PNG")

_CODE_RE = re.compile(r"^[A-Z0-9&]{2,6}$")        # trailing name-codes like LGSV, EVLT, UGF
# Date, then an OPTIONAL separator, then the position token. Optional separator
# recovers names like "2023 03 10A.jpg" (position stuck to the day).
_FILE_RE = re.compile(r"^(\d{4})[ ._-]?(\d{1,2})[ ._-]?(\d{1,2})[ ._-]*(.+)$")


def normalize_code(raw: str) -> str | None:
    """Reduce a raw filename position token to its base position letter.

    'A2' -> 'A', 'DRGSV' -> 'D', 'PHOTOD' -> 'D', 'C(2)' -> 'C', 'CEDITED' -> 'C',
    'E3' -> 'E'. Returns None for things that aren't a single position letter
    (e.g. 'JAMIEROGERS', 'B&C', 'DEMOGRAPHICPIC') so they surface for review.
    """
    s = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    if s.startswith("PHOTO"):
        s = s[5:]
    changed = True
    while changed:
        changed = False
        for suf in _CODE_SUFFIXES:
            if s.endswith(suf) and len(s) > len(suf):
                s = s[: -len(suf)]
                changed = True
        s2 = re.sub(r"\d+$", "", s)        # trailing sequence index (A2, D5…)
        if s2 != s:
            s, changed = s2, True
    return s if (len(s) == 1 and s.isalpha()) else None


def proposed_target(raw: str) -> str:
    """What the map template pre-fills for a raw code."""
    base = normalize_code(raw)
    if base in BASE_TO_SLUG:
        return BASE_TO_SLUG[base]
    return "REVIEW"


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def parse_patient_folder(name: str) -> tuple[str, str]:
    """'Aalders, Randall LGSV EVLT' -> ('Randall', 'Aalders'). Returns
    (first_name, last_name); last is '' if there's no comma."""
    name = (name or "").strip()
    if "," in name:
        last, rest = name.split(",", 1)
    else:
        last, rest = name, ""
    last = last.strip()
    tokens = rest.strip().split()
    # Drop trailing ALL-CAPS service/leg codes (LGSV, EVLT, UGF, RGSV, …).
    while tokens and _CODE_RE.match(tokens[-1]):
        tokens.pop()
    first = " ".join(tokens).strip()
    return first, last


def parse_photo_file(stem: str) -> tuple[str, str] | None:
    """'2023 03 10 A' -> ('2023-03-10', 'A'). Returns (iso_date, CODE) or None."""
    m = _FILE_RE.match(stem.strip())
    if not m:
        return None
    y, mo, d, rest = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d))
    except ValueError:
        return None
    code = re.sub(r"\s+", "", rest).upper()
    if not code:
        return None
    return dt.strftime("%Y-%m-%d"), code      # always zero-padded


def is_image(p: Path) -> bool:
    return (p.suffix.lower() in IMAGE_EXTS
            and not p.name.startswith(".")        # skip .DS_Store, ._resource forks
            and p.is_file())


def walk_archive(root: Path):
    """Yield (patient_folder_name, file_path) for every image under root.
    The patient folder is the image's immediate parent."""
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = Path(dirpath) / fn
            if is_image(p):
                yield Path(dirpath).name, p


# --------------------------------------------------------------------------- #
# Scan
# --------------------------------------------------------------------------- #
def scan(root: Path) -> dict:
    code_counts: dict[str, int] = defaultdict(int)
    patients: dict[tuple[str, str], dict] = {}
    unparsed_files: list[str] = []
    unsupported: list[str] = []
    bad_folders: list[str] = []

    # Note unsupported image types (e.g. HEIC) so nothing is silently dropped.
    for dirpath, _d, filenames in os.walk(root):
        for fn in filenames:
            if fn.startswith("."):
                continue
            if Path(fn).suffix.lower() in OTHER_IMAGE_EXTS:
                unsupported.append(str(Path(dirpath) / fn))

    for folder, path in walk_archive(root):
        first, last = parse_patient_folder(folder)
        if not last and not first:
            bad_folders.append(folder)
            continue
        key = (last.lower(), first.lower())
        rec = patients.setdefault(key, {
            "first_name": first, "last_name": last,
            "folders": set(), "photo_count": 0, "codes": defaultdict(int),
        })
        rec["folders"].add(folder)
        parsed = parse_photo_file(path.stem)
        if not parsed:
            unparsed_files.append(str(path))
            continue
        _date, code = parsed
        rec["photo_count"] += 1
        rec["codes"][code] += 1
        code_counts[code] += 1

    # Which parsed patients already exist locally (match) vs would be created.
    existing = 0
    for (last_l, first_l), rec in patients.items():
        match = db.find_patient_by_name(rec["first_name"], rec["last_name"])
        rec["match_id"] = match["id"] if match else None
        if match:
            existing += 1

    manifest = {
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "totals": {
            "patients": len(patients),
            "patients_matching_existing": existing,
            "patients_new": len(patients) - existing,
            "photos_parsed": sum(r["photo_count"] for r in patients.values()),
            "codes": dict(sorted(code_counts.items(), key=lambda kv: -kv[1])),
            "unparsed_files": len(unparsed_files),
            "unsupported_files": len(unsupported),
            "unreadable_folders": len(bad_folders),
        },
        "patients": [
            {
                "first_name": r["first_name"], "last_name": r["last_name"],
                "photo_count": r["photo_count"],
                "codes": dict(r["codes"]),
                "folders": sorted(r["folders"]),
                "matches_patient_id": r["match_id"],
            }
            for r in sorted(patients.values(),
                            key=lambda r: (r["last_name"].lower(), r["first_name"].lower()))
        ],
        "unparsed_files_sample": unparsed_files[:40],
        "unsupported_files_sample": unsupported[:40],
        "unreadable_folders_sample": bad_folders[:40],
    }
    return manifest


def write_map_template(code_counts: dict[str, int]) -> None:
    # Auto-fill every raw code via the normalizer; A/B/C/D variants resolve to a
    # slug, everything else is left "REVIEW". Kept keyed by RAW code so the map
    # is fully auditable — you can see exactly what each on-disk token becomes.
    mapping = {}
    for code in sorted(code_counts, key=lambda c: -code_counts[c]):
        mapping[code] = proposed_target(code)
    doc = {
        "_help": {
            "each key": "a position code found in your filenames (raw, as on disk)",
            "set each value to": [
                "a position slug (e.g. legs-front, left-leg-side, right-leg-side, legs-back)",
                "'headshot'  → use the most recent such photo as the patient's profile photo",
                "'skip'      → ignore this code",
            ],
            "already filled": "A/B/C/D and all their variants (A2, DRGSV, PHOTOA…) are set for you.",
            "you decide": "only the ones still marked REVIEW (new position letters + oddities).",
            "existing slugs": [p["slug"] for p in db.list_photo_positions(active_only=False)],
            "note": "Any slug you invent (e.g. 'face', 'left-hand') is created automatically on commit.",
        },
        "map": mapping,
        "counts": dict(sorted(code_counts.items(), key=lambda kv: -kv[1])),
    }
    MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    MAP_FILE.write_text(json.dumps(doc, indent=2))


# --------------------------------------------------------------------------- #
# Commit
# --------------------------------------------------------------------------- #
def load_ledger() -> set[str]:
    if LEDGER_FILE.exists():
        return {ln.strip() for ln in LEDGER_FILE.read_text().splitlines() if ln.strip()}
    return set()


def append_ledger(fh, rel: str) -> None:
    fh.write(rel + "\n")
    fh.flush()


def slug_to_name(slug: str) -> str:
    return slug.replace("-", " ").title()


def resolve_positions(mapping: dict[str, str]) -> dict[str, dict]:
    """code -> {'kind':'position','position':<row>} | {'kind':'headshot'} | {'kind':'skip'}."""
    by_slug = {p["slug"]: p for p in db.list_photo_positions(active_only=False)}
    out: dict[str, dict] = {}
    sort_base = max([p.get("sort_order", 0) for p in by_slug.values()] + [0])
    for code, target in mapping.items():
        t = (target or "").strip().lower()
        if t in ("skip", "", "review", "ignore"):
            out[code] = {"kind": "skip"}
        elif t == "headshot":
            out[code] = {"kind": "headshot"}
        else:
            row = by_slug.get(t)
            if not row:
                sort_base += 10
                pid = db.create_photo_position(slug_to_name(t), t, body_area="other",
                                               sort_order=sort_base)
                row = db.get_photo_position(pid)
                by_slug[t] = row
                print(f"  + created photo position '{t}' (id {pid})")
            out[code] = {"kind": "position", "position": row}
    return out


def commit(root: Path, mapping: dict[str, str], only: str, limit: int, created_by: str) -> None:
    manifest = scan(root)
    code_counts = manifest["totals"]["codes"]

    # Every code present must have a decision.
    missing = [c for c in code_counts if c not in mapping or
               (mapping[c] or "").strip().lower() in ("", "review")]
    if missing:
        print("STOP — these codes have no decision in the map (edit "
              f"{MAP_FILE} and set each to a slug / 'headshot' / 'skip'):")
        for c in missing:
            print(f"    {c}   ({code_counts[c]} files)")
        sys.exit(2)

    resolved = resolve_positions(mapping)
    ledger = load_ledger()

    # Re-group archive files by parsed patient, keeping full paths.
    by_patient: dict[tuple[str, str], dict] = {}
    for folder, path in walk_archive(root):
        first, last = parse_patient_folder(folder)
        if not last and not first:
            continue
        key = (last.lower(), first.lower())
        rec = by_patient.setdefault(key, {"first_name": first, "last_name": last, "files": []})
        parsed = parse_photo_file(path.stem)
        if parsed:
            rec["files"].append((parsed[0], parsed[1], path))   # (iso_date, code, path)

    keys = sorted(by_patient, key=lambda k: (k[0], k[1]))
    if only:
        o = only.lower()
        keys = [k for k in keys if o in (by_patient[k]["last_name"] + " "
                                         + by_patient[k]["first_name"]).lower()]
    if limit:
        keys = keys[:limit]

    stats = {"patients_created": 0, "patients_matched": 0, "photos": 0,
             "headshots": 0, "skipped_existing": 0, "errors": 0}

    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_FILE.open("a") as led:
        for key in keys:
            rec = by_patient[key]
            match = db.find_patient_by_name(rec["first_name"], rec["last_name"])
            if match:
                patient = match
                stats["patients_matched"] += 1
            else:
                pid = db.create_patient(first_name=rec["first_name"], last_name=rec["last_name"],
                                        created_by=created_by)
                patient = db.get_patient(pid)
                stats["patients_created"] += 1
            label = f"{rec['first_name']} {rec['last_name']}".strip()
            print(f"• {label}  ({len(rec['files'])} files)")

            # Group this patient's files by code.
            by_code: dict[str, list] = defaultdict(list)
            for iso_date, code, path in rec["files"]:
                by_code[code].append((iso_date, path))

            for code, items in by_code.items():
                decision = resolved.get(code, {"kind": "skip"})
                items.sort(key=lambda t: t[0])          # chronological (oldest first)

                if decision["kind"] == "skip":
                    continue

                if decision["kind"] == "headshot":
                    iso_date, path = items[-1]           # most recent face shot
                    rel = str(path)
                    if rel in ledger:
                        stats["skipped_existing"] += 1
                        continue
                    try:
                        saved = photos_svc.store_headshot(patient, path.read_bytes())
                        db.set_patient_headshot(patient["id"], saved["headshot_path"],
                                                saved["thumb_path"])
                        append_ledger(led, rel)
                        stats["headshots"] += 1
                    except Exception as exc:  # noqa: BLE001
                        print(f"    ! headshot failed ({path.name}): {exc}")
                        stats["errors"] += 1
                    continue

                # A clinical position: import the whole series chronologically.
                position = decision["position"]
                prev = db.latest_patient_photo(patient["id"], position["id"])
                prev_std = prev["std_path"] if prev else None
                for iso_date, path in items:
                    rel = str(path)
                    if rel in ledger:
                        stats["skipped_existing"] += 1
                        continue
                    try:
                        taken = datetime.strptime(iso_date, "%Y-%m-%d")
                        meta = photos_svc.store(patient, position, path.read_bytes(),
                                                taken_by=created_by, prev_std_rel=prev_std,
                                                taken_at=taken)
                        db.add_patient_photo(
                            patient["id"], position["id"], position["name"],
                            meta["orig_path"], meta["std_path"], meta["thumb_path"],
                            meta["width"], meta["height"], meta["framing_score"],
                            meta["framing_note"], created_by,
                            created_at=f"{iso_date}T00:00:00", source="import")
                        prev_std = meta["std_path"]
                        append_ledger(led, rel)
                        stats["photos"] += 1
                    except Exception as exc:  # noqa: BLE001
                        print(f"    ! photo failed ({path.name}): {exc}")
                        stats["errors"] += 1

    print("\n=== Import complete ===")
    for k, v in stats.items():
        print(f"  {k.replace('_',' ')}: {v}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def human_scan_summary(m: dict) -> None:
    t = m["totals"]
    print(f"\nArchive: {m['root']}")
    print(f"  Patients found:        {t['patients']}  "
          f"({t['patients_matching_existing']} match existing, {t['patients_new']} new)")
    print(f"  Photos that parsed:    {t['photos_parsed']}")
    print(f"  Did NOT parse:         {t['unparsed_files']} files")
    print(f"  Unsupported (e.g HEIC):{t['unsupported_files']} files")
    print(f"  Unreadable folders:    {t['unreadable_folders']}")

    # Roll the raw codes up to base positions so the picture is readable.
    rollup: dict[str, int] = {}
    variants: dict[str, set] = {}
    review: dict[str, int] = {}
    for code, n in t["codes"].items():
        base = normalize_code(code)
        if base in BASE_TO_SLUG:
            rollup[base] = rollup.get(base, 0) + n
            variants.setdefault(base, set()).add(code)
        elif base:                       # a clean single letter, but no label yet
            review[base] = review.get(base, 0) + n
        else:                            # not a position letter at all
            review.setdefault("(odd)", 0)
            review["(odd)"] += n
    print("\n  Rolled up by position (variants merged):")
    for base in sorted(rollup):
        vs = ", ".join(sorted(variants[base]))
        print(f"      {base} → {BASE_TO_SLUG[base]:<16} {rollup[base]:>6}   [{vs}]")
    if review:
        print("\n  NEEDS A DECISION (new position letters + oddities) — set these in the map:")
        for code in sorted(review, key=lambda c: -review[c]):
            print(f"      {code:<8} {review[code]:>6}  (likely face / hand / neckline, or junk → skip)")

    sample = [os.path.basename(p) for p in m.get("unparsed_files_sample", [])][:15]
    if sample:
        print("\n  Sample of filenames that did NOT parse (paste these to me):")
        for s in sample:
            print(f"      {s}")

    print(f"\n  Full manifest : {SCAN_FILE}")
    print(f"  Edit this map : {MAP_FILE}   (REVIEW entries only — A/B/C/D are done)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Review-first import of the CLIENT PHOTOS archive.")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="Path to the CLIENT PHOTOS folder.")
    ap.add_argument("--scan", action="store_true", help="Discover structure only (default).")
    ap.add_argument("--commit", action="store_true", help="Create patients + import photos.")
    ap.add_argument("--map", default=str(MAP_FILE), help="Position-code map JSON (for --commit).")
    ap.add_argument("--only", default="", help="Only patients whose name contains this (a test).")
    ap.add_argument("--limit", type=int, default=0, help="Only the first N patients (a test).")
    ap.add_argument("--created-by", default="photo-import")
    args = ap.parse_args()

    db.init_db()   # make sure new columns (headshot, source) exist
    root = Path(os.path.expanduser(args.root))
    if not root.exists():
        print(f"ERROR: archive folder not found: {root}")
        sys.exit(1)

    print(f"Database : {db.DB_PATH.resolve()}")
    print(f"Photos   : {Path(config.photos_path()).resolve()}")

    if args.commit:
        mp = Path(args.map)
        if not mp.exists():
            print(f"ERROR: map file not found: {mp}  (run --scan first, then edit it)")
            sys.exit(1)
        doc = json.loads(mp.read_text())
        mapping = doc.get("map", doc)     # accept either the template or a bare {code:target}
        commit(root, mapping, args.only, args.limit, args.created_by)
        return

    # Default: scan.
    manifest = scan(root)
    SCAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCAN_FILE.write_text(json.dumps(manifest, indent=2))
    write_map_template(manifest["totals"]["codes"])
    human_scan_summary(manifest)


if __name__ == "__main__":
    main()
