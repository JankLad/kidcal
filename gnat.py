#!/usr/bin/env python3
"""
KidCal — GNAT-TV / Tockify adapter.

GNAT-TV (Greater Northshire Access Television) publishes a regional community
events calendar for the mountain towns via Tockify (public slug "gnatevents").
Tockify serves NO working iCal feed — every /api/feeds/ics/<slug|calid> path
404s (calid is 62d9bf3c0b3b13562efb42b0) — but its JSON event API does:

    https://tockify.com/api/ngevent?calname=gnatevents&startms=<epoch_ms>&max=<n>

Each event carries content.summary.text, content.location.{name,address}, and
when.start/end.millis. This pulls upcoming events, converts the epoch millis to
US-Eastern wall time with a MANUAL DST rule (no zoneinfo/tzdata dependency, so
it behaves identically on Windows and the ubuntu CI runner), and emits
ingest.parse_ics-shaped dicts.

It is a REGIONAL aggregator (Manchester/Arlington-heavy), so the source is
scope "regional": build.py's in-radius town gate drops the far events and the
age filter drops adult programming — only in-radius kid/family events survive.

Standard-library only. Test:  python gnat.py gnatevents
"""

import json
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from mec import _lines_for

API = "https://tockify.com/api/ngevent"
UA = {"User-Agent": "Mozilla/5.0 (KidCal calendar aggregator)"}
MAX_EVENTS = 120


def _calname(src: str) -> str:
    """Accept a bare calname or any tockify URL (…/<calname> or ?calname=…)."""
    m = re.search(r"[?&]calname=([^&]+)", src)
    if m:
        return m.group(1)
    m = re.search(r"tockify\.com/([A-Za-z0-9_.-]+)", src)
    return m.group(1) if m else src.strip().rstrip("/").split("/")[-1]


def _et_offset(dt_utc: datetime) -> int:
    """US-Eastern UTC offset (hours) for a UTC datetime, via the standard rule:
    EDT (-4) from the 2nd Sunday of March to the 1st Sunday of November, else
    EST (-5). Deliberately avoids zoneinfo/tzdata so Windows (often no IANA db)
    and the ubuntu CI runner produce the same times. The ~2-hour slop at the DST
    transition is immaterial for a day-level community calendar."""
    y = dt_utc.year
    mar = datetime(y, 3, 1)
    dst_start = mar + timedelta(days=(6 - mar.weekday()) % 7 + 7)   # 2nd Sunday of March
    nov = datetime(y, 11, 1)
    dst_end = nov + timedelta(days=(6 - nov.weekday()) % 7)         # 1st Sunday of November
    return -4 if dst_start <= dt_utc < dst_end else -5


def _local(ms: int) -> datetime:
    utc = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)
    return utc + timedelta(hours=_et_offset(utc))


def fetch_events(src: str, default_location: str = "") -> list[dict]:
    calname = _calname(src)
    now = int(time.time() * 1000)
    url = f"{API}?calname={calname}&startms={now}&max={MAX_EVENTS}"
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - report nothing, let build.py continue
        return []

    out: list[dict] = []
    for e in data.get("events", []):
        content = e.get("content", {}) or {}
        summ = content.get("summary", {}) or {}
        title = (summ.get("text") if isinstance(summ, dict) else summ) or ""
        title = re.sub(r"\s+", " ", str(title)).strip()[:120]
        if not title:
            continue
        when = e.get("when", {}) or {}
        start = when.get("start", {}) or {}
        sms = start.get("millis") if isinstance(start, dict) else None
        if not sms:
            continue
        sdt = _local(int(sms))
        date8 = sdt.strftime("%Y%m%d")
        # Tockify stores all-day events at local midnight → emit a DATE-only line.
        start_hm = end_hm = None
        if not (sdt.hour == 0 and sdt.minute == 0):
            start_hm = (sdt.hour, sdt.minute)
            end = when.get("end", {}) or {}
            ems = end.get("millis") if isinstance(end, dict) else None
            if ems:
                edt = _local(int(ems))
                if edt > sdt:
                    end_hm = (edt.hour, edt.minute)
        dtstart, dtend = _lines_for(date8, start_hm, end_hm)

        loc = content.get("location", {}) or {}
        if isinstance(loc, dict):
            lname = " ".join(
                x for x in (loc.get("name"), loc.get("address")) if x).strip()
        else:
            lname = str(loc or "")
        desc = content.get("description", {}) or {}
        dtext = (desc.get("text") if isinstance(desc, dict) else desc) or ""
        dtext = re.sub(r"\s+", " ", str(dtext)).strip()[:400]
        # GNAT titles carry the town ("... in Londonderry"), but build.py's
        # regional radius gate inspects only location+description — so fold the
        # title in, else an in-radius event whose town is only in the title
        # (e.g. "Weekly Story Time in Londonderry") gets wrongly dropped.
        description = (f"{title} — {dtext}" if dtext else title)[:450]

        out.append({
            "summary": title,
            "start_date": date8,
            "dtstart_line": dtstart,
            "dtend_line": dtend,
            "location": lname or default_location,
            "url": f"https://tockify.com/{calname}",
            "description": description,
            "rrule": None,
        })
    return out


if __name__ == "__main__":
    import sys
    import ingest
    evs = fetch_events(sys.argv[1] if len(sys.argv) > 1 else "gnatevents")
    print(f"{len(evs)} GNAT events")
    for e in sorted(evs, key=lambda x: x["start_date"]):
        ok, _ = ingest.keep_event(e["summary"], e["description"])
        tag = "KEEP" if ok else "drop"
        t = e["dtstart_line"].split(":", 1)[1]
        print(f"  [{tag}] {e['start_date']} {t:<16} {e['summary'][:45]} | {e['location'][:25]}")
