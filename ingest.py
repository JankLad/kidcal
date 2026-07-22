#!/usr/bin/env python3
"""
KidCal — ingest: fetch and parse external .ics feeds, then age-filter.

Standard-library only. Timezone handling is pass-through: we keep each event's
original DTSTART/DTEND property lines verbatim (TZID or UTC), so no timezone
math or tzdata dependency is needed. The age filter (tuned for a 4-year-old)
decides which events belong on Sylvie's calendar.
"""

import urllib.request
from datetime import date

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KidCal/1.0"

# --- Age filter (see plan §4.3) ---------------------------------------------
# HARD_EXCLUDE always wins — a "Teen Craft" or "Adult" event is not for a 4-yo
# even though it contains a craft/activity word.
HARD_EXCLUDE = [
    "teen", "tween", "young adult", " ya ", "grades 6", "grade 6", "grade 7",
    "grade 8", "grades 7", "grades 8", "middle school", "high school",
    "adult", "adults", "18+", "21+", "grown-ups night",
]
STRONG_INCLUDE = [
    "storytime", "story time", "story hour", "playgroup", "preschool",
    "toddler", "baby", "babies", "rhyme time", "music together", "sing & dance",
    "sing and dance", "puppet", "lego", "steam", "kids", "kid ", "kid'",
    "children", "childrens", "children's", "tot ", "tots", "family storytime",
    "read to a dog", "read with a dog", "birth to", "ages 2", "ages 3", "ages 4",
    "ages 5", "under 6", "0-5", "under 5", "wiggle", "reptiles", "build a rama",
]
INCLUDE = [
    "family", "all ages", "all-ages", "movies for kids", "movie for kids",
    "pumpkin", "apple picking", "maple", "petting", "farm animals", "fairy",
]
SOFT_EXCLUDE = [
    "mahjong", "trivia", "book club", "reading group", "board of trustees",
    "board meeting", "makerspace open", "makerspace closed", "wifi", "wi-fi",
    "genealogy", "tax ", "medicare", "knitting", "in stitches", "wine", "beer",
    "job ", "resume", "town meeting", "select board", "budget", "writers group",
    "memoir", "depression", "holistic", "felting", "community read",
    "community conversation", "reel night out", "game cafe", "game café",
    "sweetgrass", "needle",
]


def keep_event(summary: str, description: str = "") -> tuple[bool, str]:
    title = summary.lower()
    full = f"{summary} {description}".lower()
    if any(k in full for k in HARD_EXCLUDE):
        return False, "hard-excluded"
    # A strong keyword in the TITLE is decisive (e.g. "Preschool Storytime").
    if any(k in title for k in STRONG_INCLUDE):
        return True, "title-strong"
    # Otherwise soft-exclude wins over a keyword that only appears in the blurb.
    if any(k in full for k in SOFT_EXCLUDE):
        return False, "soft-excluded"
    if any(k in full for k in STRONG_INCLUDE):
        return True, "desc-strong"
    if any(k in full for k in INCLUDE):
        return True, "family"
    return False, "ambiguous"


# --- Fetch + parse ----------------------------------------------------------
def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def unfold(text: str) -> list[str]:
    """RFC 5545 line unfolding: continuation lines start with space or tab."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n").replace("\\N", "\n")
        .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    )


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def parse_ics(text: str) -> list[dict]:
    events: list[dict] = []
    cur: dict | None = None
    in_alarm = False
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur, in_alarm = {}, False
            continue
        if line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
            continue
        if cur is None:
            continue
        if line == "BEGIN:VALARM":
            in_alarm = True
            continue
        if line == "END:VALARM":
            in_alarm = False
            continue
        if in_alarm or ":" not in line:
            continue
        name_params, value = line.split(":", 1)
        name = name_params.split(";", 1)[0].upper()
        if name == "SUMMARY":
            cur["summary"] = unescape(value)
        elif name == "LOCATION":
            cur["location"] = unescape(value)
        elif name == "URL":
            cur["url"] = value
        elif name == "DESCRIPTION":
            cur["description"] = unescape(value)
        elif name == "UID":
            cur["uid"] = value
        elif name == "RRULE":
            cur["rrule"] = value
        elif name == "DTSTART":
            cur["dtstart_line"] = line
            cur["start_date"] = _digits(value)[:8] or None
        elif name == "DTEND":
            cur["dtend_line"] = line
    return events


def weekday_of(yyyymmdd: str) -> int | None:
    if not yyyymmdd or len(yyyymmdd) < 8:
        return None
    try:
        return date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8])).weekday()
    except ValueError:
        return None
