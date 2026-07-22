#!/usr/bin/env python3
"""
KidCal — build: assemble the calendar from the verified seed + live feeds.

Pipeline: seed events (schema A: local time + RRULE) form the verified backbone;
each source in data/sources.json is fetched, parsed, and age-filtered; feed
events that duplicate a seed event (same weekday + similar title) are dropped so
nothing double-lists; the rest are merged and written to public/kidevents.ics.

Standard-library only. Run:  python build.py   (then python publish_github.py)
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import ingest
from generate_ics import (
    CAL_NAME, PRODID, TZID, VTIMEZONE, build_vevent, escape_text, fold,
)

ROOT = Path(__file__).resolve().parent
SEED = ROOT / "data" / "seed_events.json"
SOURCES = ROOT / "data" / "sources.json"
OUT = ROOT / "public" / "kidevents.ics"

BYDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

# Towns within ~30 mi of Bellows Falls (plan §2). Used to gate REGIONAL
# aggregator sources whose events can range far outside the radius.
IN_RADIUS_TOWNS = {
    "bellows falls", "rockingham", "saxtons river", "westminster", "athens",
    "grafton", "putney", "dummerston", "brattleboro", "newfane", "townshend",
    "jamaica", "chester", "springfield", "cavendish", "proctorsville", "ludlow",
    "weston", "londonderry", "andover", "windsor", "perkinsville", "walpole",
    "charlestown", "alstead", "langdon", "acworth", "marlow", "surry", "gilsum",
    "westmoreland", "keene", "swanzey", "hinsdale", "claremont",
}


def in_radius_text(text: str) -> bool:
    t = text.lower()
    return any(town in t for town in IN_RADIUS_TOWNS)
STOP = {
    "the", "on", "a", "an", "at", "with", "and", "for", "of", "to", "in",
    "library", "memorial", "free", "public", "brooks", "keene", "rockingham",
    "brattleboro", "commons", "common", "vt", "nh",
}


def title_tokens(t: str) -> set[str]:
    words = re.sub(r"[^a-z0-9]+", " ", t.lower()).split()
    return {w for w in words if w not in STOP and len(w) > 1}


def seed_weekday(ev: dict) -> int | None:
    m = re.search(r"BYDAY=([A-Z,]+)", ev.get("rrule", "") or "")
    if not m:
        return None
    return BYDAY.get(m.group(1).split(",")[0])


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def duplicates_seed(feed_ev: dict, seeds: list[dict]) -> bool:
    fday = ingest.weekday_of(feed_ev.get("start_date", ""))
    ftok = title_tokens(feed_ev.get("summary", ""))
    for s in seeds:
        if seed_weekday(s) == fday and jaccard(ftok, title_tokens(s["title"])) >= 0.5:
            return True
    return False


def feed_uid(source: str, ev: dict) -> str:
    key = f"{source}|{ev.get('summary','')}|{ev.get('start_date','')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + "@kidcal"


def emit_feed_vevent(ev: dict, source: str, dtstamp: str) -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:{feed_uid(source, ev)}", f"DTSTAMP:{dtstamp}"]
    lines.append(ev["dtstart_line"])
    if ev.get("dtend_line"):
        lines.append(ev["dtend_line"])
    if ev.get("rrule"):
        lines.append(f"RRULE:{ev['rrule']}")
    lines.append("SUMMARY:" + escape_text(ev.get("summary", "Event")))
    if ev.get("location"):
        lines.append("LOCATION:" + escape_text(ev["location"]))
    if ev.get("url"):
        lines.append("URL:" + ev["url"])
    lines.append("CATEGORIES:" + escape_text(f"kids,{source}"))
    desc = (ev.get("description", "") or "").strip()
    desc = (desc + f"\nSource: {source}").strip()
    lines.append("DESCRIPTION:" + escape_text(desc))
    lines.append("END:VEVENT")
    return lines


def build(seed: list[dict], feed_items: list[tuple[dict, str]]) -> str:
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CAL_NAME}", "X-WR-TIMEZONE:" + TZID,
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H",
    ]
    lines += VTIMEZONE
    for ev in seed:
        lines += build_vevent(ev, dtstamp)
    for ev, source in feed_items:
        lines += emit_feed_vevent(ev, source, dtstamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def main() -> None:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))

    kept: list[tuple[dict, str]] = []
    seen: set[tuple] = set()
    for src in sources:
        name = src["name"]
        scope = src.get("scope", "venue")
        try:
            raw = ingest.fetch(src["url"])
            events = ingest.parse_ics(raw)
        except Exception as e:  # noqa: BLE001 - report and continue
            print(f"  ! {name}: fetch/parse failed: {e}")
            continue
        n_kept = n_age = n_dup = n_geo = 0
        for ev in events:
            if not ev.get("start_date") or not ev.get("dtstart_line"):
                continue
            ok, _ = ingest.keep_event(ev.get("summary", ""), ev.get("description", ""))
            if not ok:
                n_age += 1
                continue
            # Regional aggregators can list far-away events — require an
            # in-radius town in the location/description.
            if scope == "regional" and not in_radius_text(
                f"{ev.get('location','')} {ev.get('description','')}"
            ):
                n_geo += 1
                continue
            if duplicates_seed(ev, seed):
                n_dup += 1
                continue
            key = (name, ev.get("summary", ""), ev.get("start_date", ""))
            if key in seen:
                continue
            seen.add(key)
            kept.append((ev, name))
            n_kept += 1
        print(f"  {name}: {len(events)} feed -> kept {n_kept} "
              f"(dropped {n_age} off-age, {n_geo} out-of-radius, {n_dup} dup-of-seed)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(seed, kept), encoding="utf-8", newline="")
    print(f"Wrote {len(seed)} seed + {len(kept)} feed = "
          f"{len(seed) + len(kept)} events -> {OUT}")


if __name__ == "__main__":
    main()
