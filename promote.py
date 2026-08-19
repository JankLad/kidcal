#!/usr/bin/env python3
"""
KidCal — promote: turn APPROVED Facebook flyer candidates into live calendar
events, then publish — no hand-editing seed JSON, no manual git.

The weekly local harvest (browser_pass.py --cookies -> flyer.py) fills
data/flyer_candidates.json with QUARANTINED candidates. Flyer text is noisy
(ads, memes, multiple dates), so which candidate is a real event — and its
exact date — stays a human call. But everything MECHANICAL around that call is
automated here:

    python promote.py --draft
        Scaffold data/flyer_approved.json from the current candidates, each
        pre-filled with a best-guess title + start_local and "approve": false.
        Open it, flip "approve": true on the real ones and fix the date/title.
        Re-running --draft KEEPS your existing edits and only adds new finds.

    python promote.py
        Promote every approve:true entry into data/seed_events.json (dedup by
        title+date), rebuild the calendar (build.py), and PUSH both
        data/seed_events.json and the built kidevents.ics to GitHub via the same
        Contents API publish_github.py uses. Start-to-end automatic once ticked.

So the ONLY human step is ticking/date-fixing approvals; harvest, promote,
build and publish are automated. Standard-library only. Runs LOCALLY (like the
harvest) — it is never part of the cloud Action.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import flyer_run  # reuse fingerprint() so ids match the review file
import ingest      # reuse keep_event() for the relevance half of the junk-gate

ROOT = Path(__file__).resolve().parent
PY = sys.executable
CANDIDATES = ROOT / "data" / "flyer_candidates.json"
APPROVED = ROOT / "data" / "flyer_approved.json"
SEED = ROOT / "data" / "seed_events.json"
ICS = ROOT / "public" / "kidevents.ics"

MONTHS = {m[:3]: i for i, m in enumerate(
    "january february march april may june july august september october "
    "november december".split(), start=1)}

# --- OPT-OUT junk gate ---------------------------------------------------------
# Dan set the process to OPT-OUT (2026-08-18): candidates default to approve:true
# and auto-promote. This gate is the ONLY thing that auto-opts a candidate OUT —
# so obvious non-events (OCR'd ads, past/mis-dated posts, senior/civic notices)
# don't reach the live calendar. Everything else rides through automatically.
# A human can still override either way by editing approve in flyer_approved.json.
_AD_JUNK = re.compile(
    r"\b(usps|tracking|parcel|airport transportation|reliable rides|photo\s?session|"
    r"open enrollment|medicare|insurance|for sale|real estate|missing|now hiring|"
    r"we'?re hiring|obituary|per capita|virus|thank you|submission deadline|"
    r"senior center|business card|yard sale|garage sale|estate sale|for rent|"
    r"lost dog|lost cat|found dog|road closure|road work|town meeting|"
    r"car wash|bake sale|breads and cookies|special breads|bakery|kitchen delivery|"
    r"blessed eats|donations can be made|food shelf|foodshelf|food cafc|trash|recycling|"
    r"de[\s-]?clutter|audition|volunteers needed|now accepting|summer sale|dog daze|"
    r"hiring|help wanted|rummage)\b", re.I)


def _auto_approve(title: str, start_local: str, raw: str, today: date) -> tuple[bool, str]:
    """Opt-out: return (True,'auto') unless the candidate is clearly not a
    promotable local event. Reasons are recorded for transparency."""
    if not start_local:
        return False, "no parseable date"
    try:
        d = date.fromisoformat(start_local[:10])
    except ValueError:
        return False, "bad date"
    if d < today:
        return False, "past"
    if (d - today).days > 245:      # flyers advertise near-term; a date >8mo out is
        return False, "date >8mo out (likely a resurfaced old post mis-dated forward)"
    t = title.strip().lower()
    if t.endswith("(page)") or t.endswith("(group)"):  # unparsed venue/source mush
        return False, "unparsed source-name title (curate venues by hand)"
    # Venue "JUST ANNOUNCED" show graphics OCR into unreadable titles
    # ("Announced Just Bch Thee Sinseers December") — opt them out.
    if re.match(r"(just\s+)?(lan\s+)?announced\b", t):
        return False, "venue 'just announced' graphic (garbled OCR title)"
    if _AD_JUNK.search(f"{title} {raw}"):
        return False, "ad / non-event"
    ok, _ = ingest.keep_event(title, raw)             # broad-community relevance
    if not ok:
        return False, "off-topic (relevance filter)"
    return True, "auto"


# --------------------------------------------------------------- best-guess parse
def _parse_date(raw: str, today: date) -> date | None:
    """Best-effort a raw flyer date ('August 20', 'AUG 31, 2026', '8/20/26')
    into a date, assuming this year (or next if the day already passed)."""
    raw = raw.strip()
    m = re.match(r"(?i)([a-z]{3,})\.?\s+(\d{1,2})(?:,?\s*(20\d{2}))?", raw)
    if m and m.group(1)[:3].lower() in MONTHS:
        mo, day = MONTHS[m.group(1)[:3].lower()], int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else today.year
        try:
            d = date(yr, mo, day)
        except ValueError:
            return None
        if not m.group(3) and d < today:
            try:
                d = date(yr + 1, mo, day)
            except ValueError:
                return None
        return d
    m = re.match(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", raw)
    if m:
        mo, day = int(m.group(1)), int(m.group(2))
        yr = m.group(3)
        yr = (2000 + int(yr)) if yr and len(yr) == 2 else (int(yr) if yr else today.year)
        try:
            d = date(yr, mo, day)
        except ValueError:
            return None
        if not m.group(3) and d < today:
            try:
                d = date(yr + 1, mo, day)
            except ValueError:
                return None
        return d
    return None


def _parse_time(raw: str) -> str | None:
    """First clock time in a raw string -> 'HH:MM' (24h). '6-7pm'->18:00."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?|am|pm)?", raw, re.I)
    if not m:
        return None
    h, mm = int(m.group(1)), int(m.group(2) or 0)
    ap = (m.group(3) or "").lower().replace(".", "")
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if 0 <= h <= 23:
        return f"{h:02d}:{mm:02d}"
    return None


def _guess_start(cand: dict, today: date) -> str:
    """Earliest future date in the candidate + its first time -> start_local."""
    best = None
    for raw in cand.get("dates_raw", []) or []:
        d = _parse_date(raw, today)
        if d and d >= today and (best is None or d < best):
            best = d
    if not best:
        return ""
    hm = None
    for raw in cand.get("times_raw", []) or []:
        hm = _parse_time(raw)
        if hm:
            break
    return f"{best.isoformat()}T{hm or '09:00'}"


def _guess_title(cand: dict) -> str:
    """Pull the flyer's transcribed words out of the ALT-text title, else source."""
    m = re.search(r"text that says[,:]?\s*['\"]?(.+)", cand.get("title", ""), re.I)
    if m:
        words = re.findall(r"[A-Za-z][A-Za-z'&]+", m.group(1))
        if len(words) >= 2:
            return " ".join(words[:8]).title()
    return cand.get("source", "Community event")


# ------------------------------------------------------------------------- draft
def do_draft() -> None:
    if not CANDIDATES.exists():
        sys.exit(f"No {CANDIDATES}. Run the harvest first (flyer_run.py).")
    cands = json.loads(CANDIDATES.read_text(encoding="utf-8")).get("candidates", [])
    prior = {}
    if APPROVED.exists():
        for e in json.loads(APPROVED.read_text(encoding="utf-8")).get("candidates", []):
            prior[e.get("id")] = e
    today = date.today()
    out = []
    kept_edits = 0
    for c in cands:
        if c.get("confidence") == "none":
            continue
        cid = flyer_run.fingerprint(c)
        if cid in prior:                       # preserve the human's earlier edits
            out.append(prior[cid])
            kept_edits += 1
            continue
        title = _guess_title(c)
        start_local = _guess_start(c, today)
        approve, reason = _auto_approve(title, start_local,
                                        c.get("raw_excerpt", "") or "", today)
        out.append({
            "id": cid,
            "approve": approve,      # OPT-OUT default: junk-gate decides, human can override
            "_gate": reason,
            "source": c.get("source", ""),
            "title": title,
            "start_local": start_local,
            "duration_min": 60,
            "location": c.get("location", ""),
            "category": "family",
            "age": "all ages",
            "town": "",
            "url": c.get("url", ""),
            "_dates_seen": c.get("dates_raw", []),
            "_times_seen": c.get("times_raw", []),
            "_raw": (c.get("raw_excerpt", "") or "")[:300],
        })
    APPROVED.write_text(json.dumps({
        "note": ("OPT-OUT process: candidates default to approve:true and auto-promote; "
                 "the junk-gate (_gate field) auto-opts-out obvious non-events. To keep "
                 "something off the calendar set approve:false; to rescue a gated one set "
                 "approve:true (and fix title/start_local). Fields starting with _ are "
                 "reference only. Re-running --draft keeps your edits."),
        "generated": datetime.now().isoformat(timespec="minutes"),
        "candidates": out,
    }, indent=2), encoding="utf-8")
    n_new = len(out) - kept_edits
    n_appr = sum(1 for e in out if e.get("approve") is True)
    print(f"Wrote {APPROVED}  ({len(out)} candidate(s): {kept_edits} kept, {n_new} new; "
          f"{n_appr} auto-approved, {len(out) - n_appr} gated out).")
    print("Opt-out: run  python promote.py  to publish the auto-approved ones.")


# ----------------------------------------------------------------------- promote
def _seed_from(entry: dict) -> dict:
    ev = {
        "title": entry["title"].strip(),
        "location": entry.get("location", "").strip(),
        "start_local": entry["start_local"].strip(),
        "duration_min": int(entry.get("duration_min", 60) or 60),
        "url": entry.get("url", ""),
        "source": entry.get("source", ""),
        "category": entry.get("category", "family"),
        "age": entry.get("age", "all ages"),
        "town": entry.get("town", ""),
        "description": (f"Promoted from a Facebook flyer via {entry.get('source','')}, "
                        f"{date.today().isoformat()}."),
    }
    return ev


def do_promote(push: bool = True) -> None:
    if not APPROVED.exists():
        sys.exit(f"No {APPROVED}. Run:  python promote.py --draft  first.")
    approved = json.loads(APPROVED.read_text(encoding="utf-8")).get("candidates", [])
    picks = [e for e in approved if e.get("approve") is True]
    if not picks:
        print("Nothing approved (no entry has \"approve\": true). Edit "
              f"{APPROVED.name} and re-run.")
        return

    seed = json.loads(SEED.read_text(encoding="utf-8"))
    have = {(s.get("title", "").strip().lower(), (s.get("start_local", "") or "")[:10])
            for s in seed}
    # Also key by (source, date): the auto-extracted OCR title rarely matches a
    # hand-curated title, so title-dedup alone would re-add events already
    # promoted by hand. Same source on the same day = treat as the same event.
    have_sd = {(s.get("source", "").strip().lower(), (s.get("start_local", "") or "")[:10])
               for s in seed if s.get("source")}
    added = []
    for e in picks:
        if not e.get("title", "").strip() or not e.get("start_local", "").strip():
            print(f"  ! skipped (needs title + start_local): {e.get('id')}")
            continue
        ev = _seed_from(e)
        key = (ev["title"].lower(), ev["start_local"][:10])
        sd = (ev.get("source", "").strip().lower(), ev["start_local"][:10])
        if key in have or (sd[0] and sd in have_sd):
            continue
        seed.append(ev)
        have.add(key)
        have_sd.add(sd)
        added.append(ev)

    if not added:
        print("All approved events were already in seed_events.json — nothing to add.")
        return
    SEED.write_text(json.dumps(seed, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"Added {len(added)} event(s) to {SEED.name}:")
    for ev in added:
        print(f"  + {ev['start_local']}  {ev['title']}")

    # Rebuild the calendar so the pushed ICS reflects the new events immediately.
    print("Rebuilding calendar (build.py)...")
    r = subprocess.run([PY, str(ROOT / "build.py")], cwd=ROOT,
                       capture_output=True, text=True)
    print("  " + (r.stdout.strip().splitlines() or ["(no output)"])[-1])
    if r.returncode != 0:
        sys.exit("  ! build.py failed; not pushing. " + (r.stderr or "")[-300:])

    if push:
        _push()


# -------------------------------------------------------------------------- push
def _push() -> None:
    """Push seed_events.json + the built ICS to the repo via the Contents API
    (reuses publish_github's config + token — no git needed)."""
    try:
        import os
        import publish_github as pg
    except Exception as e:  # noqa: BLE001
        print(f"  ! publish step skipped (publish_github import failed: {e}).")
        return
    token = os.environ.get("KIDCAL_GITHUB_TOKEN")
    if not token:
        print("  ! KIDCAL_GITHUB_TOKEN not set — promoted + built locally, but "
              "NOT pushed. Set the token (see publish_github.py) and re-run, or "
              "run publish_github.py to push the ICS.")
        return
    cfg = pg.load_config()
    base = f"{pg.API}/repos/{cfg['owner']}/{cfg['repo']}/contents/"
    pairs = [(SEED, "data/seed_events.json"), (ICS, cfg["path"])]
    import base64
    for local, repo_path in pairs:
        url = base + repo_path
        st, cur = pg.request("GET", f"{url}?ref={cfg['branch']}", token)
        sha = cur.get("sha") if st == 200 else None
        body = {"message": "KidCal: promote approved flyer event(s)",
                "content": base64.b64encode(local.read_bytes()).decode(),
                "branch": cfg["branch"]}
        if sha:
            body["sha"] = sha
        st, resp = pg.request("PUT", url, token, body)
        if st in (200, 201):
            print(f"  pushed {repo_path}")
        else:
            sys.exit(f"  ! push failed for {repo_path} [{st}]: {resp.get('message', resp)}")
    print("Published. The daily Action will keep it (source is now in the repo).")


def main() -> None:
    ap = argparse.ArgumentParser(description="Promote approved flyer candidates and publish.")
    ap.add_argument("--draft", action="store_true",
                    help="scaffold/refresh data/flyer_approved.json from candidates")
    ap.add_argument("--no-push", action="store_true",
                    help="promote + rebuild locally but do not push to GitHub")
    args = ap.parse_args()
    if args.draft:
        do_draft()
    else:
        do_promote(push=not args.no_push)


if __name__ == "__main__":
    main()
