#!/usr/bin/env python3
"""
KidCal — seed watcher: catch expired seeds and schedule changes.

Two jobs, both aimed at the failure mode that actually bit us: a program quietly
ends (or a new season quietly starts) and the calendar keeps looking healthy.

  1. EXPIRY WATCH — report seed events whose RRULE UNTIL has passed, so a dead
     seed can't sit in the file unnoticed. (Rockingham's summer series ended
     2026-08-15; that's exactly this case.)

  2. SCHEDULE WATCH — fetch each seed's source page and fingerprint the relevant
     text. When a library posts its fall storytime, the page text changes and
     this says so, with the weekday/time lines it found, so a human can verify
     and update the seed.

Deliberately reports rather than edits: seed events are the VERIFIED backbone,
and a scraped schedule line is not verification. Never auto-writes seeds.

Standard library only (fits the cloud job's zero-dependency rule), but this is
most useful locally alongside flyer_run.py.

Usage:
  python watch_seeds.py            # check expiry + page changes
  python watch_seeds.py --quiet    # only print when something needs attention
"""

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEED = ROOT / "data" / "seed_events.json"
STATE = ROOT / "data" / "seed_watch_state.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KidCal-SeedWatch/1.0"

# Lines that plausibly carry a recurring schedule, e.g.
# "Tuesday Preschool Storytime 10:30am" or "Fridays 10:30-12".
SCHED_RE = re.compile(
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)day[s]?[^.\n]{0,90}?"
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)",
    re.I,
)


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    html = re.sub(r"(?s)<script.*?</script>", " ", html)
    html = re.sub(r"(?s)<style.*?</style>", " ", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&#8211;", "-").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def until_of(rrule: str) -> str | None:
    m = re.search(r"UNTIL=(\d{8})", rrule or "")
    return m.group(1) if m else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true",
                    help="only output when action is needed")
    args = ap.parse_args()

    seeds = json.loads(SEED.read_text(encoding="utf-8"))
    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    pages = state.get("pages", {})

    today = datetime.now().strftime("%Y%m%d")
    alerts: list[str] = []

    # --- 1. expiry watch -----------------------------------------------------
    for ev in seeds:
        until = until_of(ev.get("rrule", ""))
        if until and until < today:
            alerts.append(
                f"EXPIRED SEED: '{ev['title']}' ended {until[:4]}-{until[4:6]}-{until[6:]}"
                f" — confirm the new season, then update or remove it."
            )

    # --- 2. schedule watch ---------------------------------------------------
    urls = sorted({ev["url"] for ev in seeds if ev.get("url")})
    for url in urls:
        try:
            text = fetch_text(url)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            alerts.append(f"UNREACHABLE: {url} ({e})")
            continue
        found = sorted({re.sub(r"\s+", " ", m.group(0)).strip()
                        for m in SCHED_RE.finditer(text)})
        digest = hashlib.sha1("|".join(found).encode("utf-8")).hexdigest()[:16]
        prev = pages.get(url, {})
        if prev.get("digest") and prev["digest"] != digest:
            alerts.append(
                f"SCHEDULE CHANGED: {url}\n"
                f"    was {len(prev.get('lines', []))} schedule line(s), "
                f"now {len(found)}:\n"
                + "\n".join(f"      - {l}" for l in found[:8])
            )
        pages[url] = {"digest": digest, "lines": found,
                      "checked": datetime.now().isoformat(timespec="minutes")}

    state["pages"] = pages
    state["last_run"] = datetime.now().isoformat(timespec="minutes")
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    if alerts:
        print(f"KidCal seed watch — {len(alerts)} item(s) need attention:\n")
        for a in alerts:
            print(f"  * {a}")
    elif not args.quiet:
        print(f"KidCal seed watch: {len(seeds)} seeds, {len(urls)} source page(s), "
              f"nothing changed.")


if __name__ == "__main__":
    main()
