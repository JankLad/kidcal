#!/usr/bin/env python3
"""
KidCal — MyRec.com adapter.

MyRec (many municipal rec depts: Windsor VT, Walpole/Grafton MA, ...) has no
public .ics feed and no per-program iCal (program_ical.aspx 404s). But each
program *detail* page carries the schedule as labeled free-text inside the
description span:

    Ages:  5 - 13
    Dates: Begins June 22nd through Aug 14th
    Days:  Mondays through Friday
    Time:  8:00 am - 4:00 pm
    Where: Rec. Center
    Fee:   $700/Res ...

So: list programs from /info/activities/ (ProgramID links), fetch each detail
page, strip HTML, regex the labeled fields, and emit a recurring VEVENT
(BYDAY from "Days", UNTIL from the end date). Confidence is inherently medium —
these are human-typed labels, not structured fields — so the age filter and the
past-date cutoff in build.py still apply. Emits ingest.parse_ics-shaped dicts.

Standard-library only. Test:  python myrec.py https://windsorvt.myrec.com
"""

import re

import ingest
from mec import _lines_for, _strip, _to24, TIME_RANGE

LIST_PATH = "/info/activities/"
DETAIL = "/info/activities/program_details.aspx?ProgramID="
MAX_PROGRAMS = 60

PROGRAM_ID = re.compile(r"program_details\.aspx\?ProgramID=(\d+)", re.I)
# Listing anchors give clean program titles (detail-page name element is unreliable).
PROGRAM_LINK = re.compile(
    r'href="[^"]*program_details\.aspx\?ProgramID=(\d+)"[^>]*>(.*?)</a>', re.I | re.S
)
LABELS = r"Ages|Dates|Days|Time|Where|Fee|Deadline|Instructors?|Grades?|Coach|Location"
DESC_SPAN = re.compile(
    r'id="Content_lblDescription"[^>]*>(.*?)</span>\s*(?:</div>|<div)', re.I | re.S
)
NAME_SPAN = re.compile(r'id="Content_lbl(?:ActivityName|Name)"[^>]*>(.*?)</span>', re.I | re.S)

MONTHS = {m[:3]: i for i, m in enumerate(
    "january february march april may june july august september october "
    "november december".split(), start=1)}
MONTH_RE = "|".join(MONTHS)
DATE_TOKEN = re.compile(rf"\b({MONTH_RE})[a-z]*\.?\s+(\d{{1,2}})", re.I)
YEAR_RE = re.compile(r"\b(20\d\d)\b")
WEEKDAYS = [("monday", "MO"), ("tuesday", "TU"), ("wednesday", "WE"),
            ("thursday", "TH"), ("friday", "FR"), ("saturday", "SA"),
            ("sunday", "SU")]
WD_ORDER = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _label(text: str, label: str) -> str:
    """Grab the value after 'Label:' up to the next labeled field or newline."""
    m = re.search(rf"{label}\s*:?\s*(.+)", text, re.I)
    if not m:
        return ""
    val = m.group(1)
    # cut at the next known label so multi-label single lines don't bleed
    val = re.split(rf"(?i)(?:{LABELS})\s*:", val, maxsplit=1)[0]
    return re.sub(r"\s+", " ", val).strip(" .- ")


def _daterange(dates_line: str, whole: str) -> tuple[str, str] | None:
    """Return (start_YYYYMMDD, end_YYYYMMDD) from a free-text date phrase.

    Only the 'Dates:' line is trusted — falling back to whole-page tokens grabs
    unrelated dates (a Deadline, "subject to change") and mis-starts the event.
    """
    toks = DATE_TOKEN.findall(dates_line)
    if not toks:
        return None
    yr_m = YEAR_RE.search(dates_line) or YEAR_RE.search(whole)
    from datetime import date
    today = date.today()
    year = int(yr_m.group(1)) if yr_m else today.year
    sm, sd = MONTHS[toks[0][0].lower()[:3]], int(toks[0][1])
    em, ed = MONTHS[toks[-1][0].lower()[:3]], int(toks[-1][1])
    # If no explicit year and the start month already passed, assume next year.
    if not yr_m and (sm, sd) < (today.month, today.day):
        year += 1
    try:
        start = date(year, sm, sd)
        end_year = year + 1 if em < sm else year
        end = date(end_year, em, ed)
    except ValueError:
        return None
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _byday(days_line: str) -> list[str]:
    low = days_line.lower()
    present = [(low.find(name), code) for name, code in WEEKDAYS if name[:-1] in low or name in low]
    present = [(i, c) for i, c in present if i >= 0]
    if not present:
        return []
    present.sort()
    codes = [c for _, c in present]
    # "Monday through Friday" style range → fill the span
    if len(codes) == 2 and re.search(r"through|thru|[-–]|to\b", low):
        a, b = WD_ORDER.index(codes[0]), WD_ORDER.index(codes[1])
        if a <= b:
            return WD_ORDER[a:b + 1]
    return sorted(set(codes), key=WD_ORDER.index)


def _parse_detail(pid: str, pg: str, default_location: str, url: str,
                  title: str = "") -> dict | None:
    ms = DESC_SPAN.search(pg)
    text = _strip(ms.group(1)) if ms else _strip(pg)
    if not title:
        nm = NAME_SPAN.search(pg)
        title = _strip(nm.group(1)) if nm else ""
    if not title:
        title = f"Program {pid}"
    title = re.sub(r"\s+", " ", title).strip(" *")[:120]

    dates_line = _label(text, "Dates")
    if not dates_line:
        return None  # no schedule → not a calendar event (e.g. a membership)
    rng = _daterange(dates_line, text)
    if not rng:
        return None
    start8, end8 = rng

    start_hm = end_hm = None
    tm = TIME_RANGE.search(_label(text, "Time") or text)
    if tm:
        start_hm = _to24(tm.group(1), tm.group(2), tm.group(3))
        end_hm = _to24(tm.group(4), tm.group(5), tm.group(6))
    dtstart, dtend = _lines_for(start8, start_hm, end_hm)

    byday = _byday(_label(text, "Days"))
    rrule = None
    if byday and end8 != start8:
        rrule = f"FREQ=WEEKLY;BYDAY={','.join(byday)};UNTIL={end8}T235959Z"

    ages = _label(text, "Ages")
    fee = _label(text, "Fee")
    where = _label(text, "Where")
    bits = [b for b in (f"Ages: {ages}" if ages else "",
                        f"Dates: {dates_line}" if dates_line else "",
                        f"Fee: {fee}" if fee else "") if b]
    return {
        "summary": title,
        "start_date": start8,
        "dtstart_line": dtstart,
        "dtend_line": dtend,
        "location": where or default_location,
        "url": url,
        "description": " | ".join(bits),
        "rrule": rrule,
    }


def fetch_events(base: str, default_location: str = "") -> list[dict]:
    base = base.rstrip("/")
    try:
        listing = ingest.fetch(base + LIST_PATH)
    except Exception:  # noqa: BLE001
        return []
    titles: dict[str, str] = {}
    for pid, raw in PROGRAM_LINK.findall(listing):
        titles.setdefault(pid, _strip(raw))
    pids: list[str] = []
    for pid in PROGRAM_ID.findall(listing):
        if pid not in pids:
            pids.append(pid)
    out: list[dict] = []
    for pid in pids[:MAX_PROGRAMS]:
        url = base + DETAIL + pid
        try:
            pg = ingest.fetch(url)
        except Exception:  # noqa: BLE001
            continue
        ev = _parse_detail(pid, pg, default_location, url, titles.get(pid, ""))
        if ev:
            out.append(ev)
    return out


if __name__ == "__main__":
    import sys
    b = sys.argv[1] if len(sys.argv) > 1 else "https://windsorvt.myrec.com"
    evs = fetch_events(b)
    print(f"{len(evs)} MyRec programs with schedules")
    for e in sorted(evs, key=lambda x: x["start_date"]):
        ok, why = ingest.keep_event(e["summary"], e["description"])
        tag = "KEEP" if ok else "drop"
        print(f"  [{tag}:{why}] {e['start_date']}  {e['summary']}")
        print(f"        {e['dtstart_line'].split(':',1)[1]}  rrule={e['rrule']}")
        print(f"        {e['description']}")
