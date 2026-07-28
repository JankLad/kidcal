#!/usr/bin/env python3
"""
KidCal — flyer adapter (LOCAL pass only; never the cloud build).

Handles the "flyer-first / social-only" source class documented in
docs/FLYER_SOURCING.md: municipal rec departments and small community groups
that publish kid programming ONLY as Facebook photo posts (flyers) + captions +
comment threads, with no parseable feed. Rockingham Recreation is the archetype.

Pipeline (see docs/FLYER_SOURCING.md §3):
  [Playwright, logged-in, residential IP]  Page Posts/Photos tab
     -> download flyer image(s) -> OCR pixels
     -> read post caption
     -> mine comment thread (org/link refs + missing fields; NOT profiles)
     ==> writes one raw text blob per flyer into data/flyer_inbox/<slug>.txt
  [this file]  data/flyer_inbox/*.txt
     -> parse_flyer_text() best-effort extract
     -> data/flyer_candidates.json  (status=quarantined, for HUMAN review)
     -> promote confirmed ones by hand into data/seed_events.json

This file implements the deterministic back half (parse + quarantine). The
upstream Playwright login + image OCR that fills the inbox is a separate local
step; until it's wired, drop flyer text into the inbox by hand (manual fast-path,
docs/FLYER_SOURCING.md §4). Standard-library only.
"""

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INBOX = ROOT / "data" / "flyer_inbox"
OUT = ROOT / "data" / "flyer_candidates.json"

MONTHS = ("january february march april may june july august september "
          "october november december").split()
MONTH_RE = "|".join(m[:3] for m in MONTHS)

# --- best-effort field extractors (flyer text is noisy; low confidence by design)

DATE_PATTERNS = [
    rf"\b(?:{MONTH_RE})[a-z]*\.?\s+\d{{1,2}}(?:\s*[-–]\s*\d{{1,2}})?(?:,?\s*20\d{{2}})?",
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
]
TIME_RE = r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?|AM|PM)\b"
AGE_RE = (r"\bages?\s*\d{1,2}\s*[-–to]{1,3}\s*\d{1,2}\b|\bgrades?\s*[kK0-9]"
          r"|\bunder\s*\d{1,2}\b|\bentering\s+grade")
COST_RE = r"\$\s?\d{1,3}(?:\.\d{2})?|\bfree\b"
REG_RE = r"(?:register|registration|sign[\s-]?up|rsvp|enroll)[^\n.]{0,80}"
URL_RE = r"https?://\S+|\b[\w.-]+\.(?:org|com|net|gov|us)(?:/\S*)?"


def _find_all(pattern: str, text: str) -> list[str]:
    seen, out = set(), []
    for m in re.finditer(pattern, text, flags=re.IGNORECASE):
        v = re.sub(r"\s+", " ", m.group(0).strip())
        if v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def parse_flyer_text(text: str, source: str, default_location: str = "",
                     url: str = "") -> dict:
    """Best-effort structured candidate from raw flyer/caption/comment text.

    Deliberately conservative and LOW confidence — output is for human review,
    never direct publish. Confidence rises with how many load-bearing fields
    (date, time, age, cost/registration) were actually found.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = next((l for l in lines if len(l) > 3), source)[:120]

    dates: list[str] = []
    for pat in DATE_PATTERNS:
        dates += _find_all(pat, text)
    times = _find_all(TIME_RE, text)
    ages = _find_all(AGE_RE, text)
    costs = _find_all(COST_RE, text)
    reg = _find_all(REG_RE, text)
    urls = _find_all(URL_RE, text)

    found = sum(bool(x) for x in (dates, times, ages, (costs or reg)))
    confidence = {0: "none", 1: "low", 2: "low", 3: "medium", 4: "high"}[found]

    return {
        "title": title,
        "source": source,
        "location": default_location,
        "url": url,
        "dates_raw": dates,
        "times_raw": times,
        "age_raw": ages,
        "cost_raw": costs,
        "registration_raw": reg,
        "links_found": [u for u in urls if "facebook.com" not in u.lower()],
        "confidence": confidence,
        "status": "quarantined",
        "needs": "Human review: confirm exact date(s)/year, age fit for ~age 4, "
                 "and registration before promoting to data/seed_events.json.",
        "raw_excerpt": text.strip()[:500],
    }


def main() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    files = sorted(INBOX.glob("*.txt"))
    if not files:
        print(f"No flyer text in {INBOX}. Drop one .txt per flyer there "
              f"(OCR output or manual transcription), then re-run. "
              f"See docs/FLYER_SOURCING.md §4.")
        return

    candidates = []
    for f in files:
        # filename convention: <source-slug>.txt ; first '||' line may carry meta
        text = f.read_text(encoding="utf-8")
        source = f.stem.replace("-", " ").title()
        loc = url = ""
        if text.startswith("SOURCE:"):
            first, _, rest = text.partition("\n")
            for part in first[len("SOURCE:"):].split("|"):
                k, _, v = part.strip().partition("=")
                if k.strip() == "name":
                    source = v.strip()
                elif k.strip() == "location":
                    loc = v.strip()
                elif k.strip() == "url":
                    url = v.strip()
            text = rest
        cand = parse_flyer_text(text, source, loc, url)
        cand["_inbox_file"] = f.name
        candidates.append(cand)
        print(f"  {f.name}: {source} -> confidence={cand['confidence']} "
              f"(dates={len(cand['dates_raw'])}, times={len(cand['times_raw'])}, "
              f"ages={len(cand['age_raw'])})")

    OUT.write_text(json.dumps(
        {"generated": datetime.now().isoformat(timespec="minutes"),
         "candidates": candidates}, indent=2), encoding="utf-8")
    print(f"Wrote {len(candidates)} quarantined candidate(s) -> {OUT}")
    print("Review, then copy confirmed events into data/seed_events.json.")


if __name__ == "__main__":
    main()
