#!/usr/bin/env python3
"""whatson.py YYYYMMDD — list KidCal events occurring on a given date.

Expands simple weekly RRULEs and includes discrete-dated events. Times shown
in US Eastern (July = EDT, UTC-4). Reads public/kidevents.ics.
"""
import sys
from datetime import date
from pathlib import Path

import ingest

BYDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
ICS = Path(__file__).resolve().parent / "public" / "kidevents.ics"


def dt_value(line: str) -> str:
    return line.split(":", 1)[1] if ":" in line else ""


def local_time(dtstart_line: str) -> str:
    val = dt_value(dtstart_line)
    if "T" not in val:
        return "all day"
    hhmm = val.split("T", 1)[1][:4]
    h, m = int(hhmm[:2]), int(hhmm[2:4])
    if val.endswith("Z"):  # UTC -> Eastern Daylight (July)
        h = (h - 4) % 24
    ampm = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{ampm}"


def occurs_on(ev: dict, target: str, twd: int) -> bool:
    sd = ev.get("start_date")
    if not sd:
        return False
    rr = ev.get("rrule", "") or ""
    if "FREQ=WEEKLY" in rr and "BYDAY=" in rr:
        days = rr.split("BYDAY=", 1)[1].split(";", 1)[0].split(",")
        if twd not in {BYDAY.get(d) for d in days}:
            return False
        if sd > target:
            return False
        if "UNTIL=" in rr:
            until = "".join(c for c in rr.split("UNTIL=", 1)[1] if c.isdigit())[:8]
            if until and until < target:
                return False
        return True
    return sd == target


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y%m%d")
    twd = date(int(target[:4]), int(target[4:6]), int(target[6:8])).weekday()
    events = ingest.parse_ics(ICS.read_text(encoding="utf-8"))
    hits = []
    for ev in events:
        if occurs_on(ev, target, twd):
            hits.append((local_time(ev["dtstart_line"]),
                         ev.get("summary", ""), ev.get("location", "")))
    hits.sort(key=lambda x: (x[0] == "all day", x[0]))
    print(f"{len(hits)} events on {target}:")
    for t, s, loc in hits:
        town = loc.split(",")[-2].strip() if loc.count(",") >= 2 else loc
        print(f"  {t:>9}  {s}" + (f"   [{town}]" if town else ""))


if __name__ == "__main__":
    main()
