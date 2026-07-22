#!/usr/bin/env python3
"""
KidCal — Phase 0 generator.

Reads data/seed_events.json and writes public/kidevents.ics, a valid
iCalendar feed that Google Calendar, Apple Calendar, and Outlook can
subscribe to. Dependency-free (Python standard library only).

Later phases replace the seed file with live scraped/feed events, but the
.ics writing, UID stability, timezone handling, and folding all stay here.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEED = ROOT / "data" / "seed_events.json"
OUT = ROOT / "public" / "kidevents.ics"

TZID = "America/New_York"
PRODID = "-//KidCal//Bellows Falls Kids Events//EN"
CAL_NAME = "KidCal — Kids' Events near Bellows Falls, VT"

# Static VTIMEZONE for US Eastern so every client renders the right local time.
VTIMEZONE = """BEGIN:VTIMEZONE
TZID:America/New_York
X-LIC-LOCATION:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE""".splitlines()


def escape_text(value: str) -> str:
    """Escape per RFC 5545 for TEXT values."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Fold a content line to 75 octets with continuation (leading space)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, chunk = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(chunk) + len(b) > 74:  # leave room; continuation adds a space
            out.append(chunk.decode("utf-8"))
            chunk = b
        else:
            chunk += b
    out.append(chunk.decode("utf-8"))
    return "\r\n ".join(out)


def stable_uid(ev: dict) -> str:
    key = f"{ev.get('source','')}|{ev['title']}|{ev['start_local']}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"{digest}@kidcal"


def fmt_local(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def build_vevent(ev: dict, dtstamp: str) -> list[str]:
    start = datetime.strptime(ev["start_local"], "%Y-%m-%dT%H:%M")
    end = start + timedelta(minutes=int(ev.get("duration_min", 60)))
    lines = ["BEGIN:VEVENT", f"UID:{stable_uid(ev)}", f"DTSTAMP:{dtstamp}"]
    lines.append(f"DTSTART;TZID={TZID}:{fmt_local(start)}")
    lines.append(f"DTEND;TZID={TZID}:{fmt_local(end)}")
    if ev.get("rrule"):
        lines.append(f"RRULE:{ev['rrule']}")
    lines.append("SUMMARY:" + escape_text(ev["title"]))
    if ev.get("location"):
        lines.append("LOCATION:" + escape_text(ev["location"]))
    if ev.get("url"):
        lines.append("URL:" + ev["url"])
    cats = [c for c in (ev.get("category"), ev.get("age")) if c]
    if cats:
        lines.append("CATEGORIES:" + escape_text(",".join(cats)))
    if ev.get("description"):
        src = ev.get("source", "")
        desc = ev["description"] + (f"\nSource: {src}" if src else "")
        lines.append("DESCRIPTION:" + escape_text(desc))
    lines.append("END:VEVENT")
    return lines


def build_calendar(events: list[dict]) -> str:
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CAL_NAME}",
        "X-WR-TIMEZONE:" + TZID,
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]
    lines += VTIMEZONE
    for ev in events:
        lines += build_vevent(ev, dtstamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def main() -> None:
    events = json.loads(SEED.read_text(encoding="utf-8"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build_calendar(events), encoding="utf-8", newline="")
    print(f"Wrote {len(events)} events -> {OUT}")


if __name__ == "__main__":
    main()
