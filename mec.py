#!/usr/bin/env python3
"""
KidCal — Modern Events Calendar (MEC) adapter.

MEC (used by Rockingham Free Public Library and other WordPress sites) has no
clean public .ics feed: event dates live in post-meta, not the REST output.
But every MEC event *page* embeds a schema.org JSON-LD block with startDate /
endDate. So: list events via the WP REST API, then read each event page's
JSON-LD for the date, plus a time range if the page shows one.

Emits event dicts shaped like ingest.parse_ics output (summary, dtstart_line,
dtend_line, start_date, location, url, description, rrule) so build.py's feed
pipeline consumes them unchanged. Standard-library only.
"""

import html
import json
import re
from datetime import datetime, timedelta

import ingest

REST_PATH = "/wp-json/wp/v2/mec-events?per_page=100&page="
MAX_EVENTS = 120

LD_START = re.compile(r'"startDate"\s*:\s*"([^"]+)"')
LD_END = re.compile(r'"endDate"\s*:\s*"([^"]+)"')
TIME_RANGE = re.compile(
    r"(\d{1,2}):(\d{2})\s*(am|pm)\s*(?:-|–|—|to)\s*(\d{1,2}):(\d{2})\s*(am|pm)", re.I
)


def _to24(h: str, m: str, ap: str) -> tuple[int, int]:
    h, m = int(h), int(m)
    ap = ap.lower()
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return h, m


def _strip(text: str) -> str:
    return html.unescape(re.sub("<[^>]+>", "", text or "")).strip()


def _lines_for(date8: str, start_hm, end_hm) -> tuple[str, str]:
    if start_hm:
        sh, sm = start_hm
        eh, em = end_hm if end_hm else ((sh + 1) % 24, sm)
        return (
            f"DTSTART;TZID=America/New_York:{date8}T{sh:02d}{sm:02d}00",
            f"DTEND;TZID=America/New_York:{date8}T{eh:02d}{em:02d}00",
        )
    nxt = (datetime.strptime(date8, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    return f"DTSTART;VALUE=DATE:{date8}", f"DTEND;VALUE=DATE:{nxt}"


def fetch_events(base: str, default_location: str = "") -> list[dict]:
    out: list[dict] = []
    seen_links: set[str] = set()
    for page in range(1, 4):
        try:
            data = json.loads(ingest.fetch(f"{base}{REST_PATH}{page}"))
        except Exception:  # noqa: BLE001
            break
        if not isinstance(data, list) or not data:
            break
        for item in data:
            link = item.get("link")
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            title = _strip(item.get("title", {}).get("rendered", ""))
            try:
                pg = ingest.fetch(link)
            except Exception:  # noqa: BLE001
                continue
            ms = LD_START.search(pg)
            if not ms:
                continue
            raw = ms.group(1)
            date8 = re.sub(r"[^0-9]", "", raw.split("T")[0])[:8]
            if len(date8) != 8:
                continue
            start_hm = end_hm = None
            if "T" in raw and re.search(r"T\d{2}:\d{2}", raw):
                tt = raw.split("T", 1)[1]
                start_hm = (int(tt[0:2]), int(tt[3:5]))
                me = LD_END.search(pg)
                if me and "T" in me.group(1):
                    et = me.group(1).split("T", 1)[1]
                    end_hm = (int(et[0:2]), int(et[3:5]))
            else:
                mr = TIME_RANGE.search(pg)
                if mr:
                    start_hm = _to24(mr.group(1), mr.group(2), mr.group(3))
                    end_hm = _to24(mr.group(4), mr.group(5), mr.group(6))
            dtstart, dtend = _lines_for(date8, start_hm, end_hm)
            out.append({
                "summary": title,
                "start_date": date8,
                "dtstart_line": dtstart,
                "dtend_line": dtend,
                "location": default_location,
                "url": link,
                "description": _strip(item.get("excerpt", {}).get("rendered", "")),
                "rrule": None,
            })
            if len(out) >= MAX_EVENTS:
                return out
    return out


if __name__ == "__main__":
    import sys
    evs = fetch_events(sys.argv[1] if len(sys.argv) > 1 else "https://rockinghamlibrary.org")
    print(f"{len(evs)} MEC events")
    for e in sorted(evs, key=lambda x: x["start_date"]):
        ok, _ = ingest.keep_event(e["summary"], e["description"])
        tag = "KEEP" if ok else "drop"
        t = e["dtstart_line"].split(":", 1)[1]
        print(f"  [{tag}] {e['start_date']}  {t:<16}  {e['summary']}")
