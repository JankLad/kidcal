#!/usr/bin/env python3
"""
KidCal — standing local flyer pass (scheduled).

This is the recurring driver that makes Facebook flyer sources arrive
AUTOMATICALLY instead of by hand. It chains the three pieces that already
exist and adds the missing scheduling/state layer:

    browser_pass.py   harvest FB flyers (Playwright, logged-in, local IP)
        -> data/flyer_inbox/*.txt
    flyer.py          parse into quarantined candidates
        -> data/flyer_candidates.json
    [this file]       diff against what we've already seen, and REPORT
        -> data/flyer_state.json     (seen-fingerprints, so runs are quiet)
        -> data/flyer_review.md      (only NEW candidates, for a 30-second read)

Why this is not in the cloud job: Facebook blocks datacenter IPs, so the cloud
build skips every `pass:local` source. This runs on Dan's machine from a
residential IP, on a Windows Scheduled Task.

Deliberately does NOT auto-publish. Flyer text is OCR/ALT-noisy and
date-ambiguous, so new finds land in a review file; confirmed ones get promoted
into data/seed_events.json. That quarantine rule is from docs/FLYER_SOURCING.md
and is not relaxed here.

Usage:
  python flyer_run.py                 # full pass: harvest -> parse -> report
  python flyer_run.py --no-harvest    # re-parse existing inbox only
  python flyer_run.py --reset-state   # forget what's been seen
"""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "flyer_state.json"
CANDIDATES = ROOT / "data" / "flyer_candidates.json"
REVIEW = ROOT / "data" / "flyer_review.md"
LOG = ROOT / "data" / "flyer_run.log"

PY = sys.executable


def log(msg: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run_step(script: str, args: list[str] | None = None) -> bool:
    """Run a pipeline step, capturing failure without killing the whole pass."""
    cmd = [PY, str(ROOT / script)] + (args or [])
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              timeout=1800)
    except subprocess.TimeoutExpired:
        log(f"  ! {script} timed out (30 min)")
        return False
    for line in (proc.stdout or "").splitlines():
        log(f"    {line}")
    if proc.returncode != 0:
        log(f"  ! {script} exited {proc.returncode}")
        for line in (proc.stderr or "").splitlines()[-8:]:
            log(f"    stderr: {line}")
        return False
    return True


def fingerprint(cand: dict) -> str:
    """Stable id for a candidate, so an unchanged flyer stays quiet next run."""
    key = "|".join([
        cand.get("source", ""),
        cand.get("title", "")[:120],
        ",".join(cand.get("dates_raw", []) or []),
        ",".join(cand.get("times_raw", []) or []),
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("  ! state file unreadable; starting fresh")
    return {"seen": {}}


def write_review(new: list[dict]) -> None:
    """Human-review file — only what's new since last run."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Flyer review — {stamp}",
        "",
        f"{len(new)} new flyer candidate(s) from the Facebook pass. These are "
        "**quarantined**: nothing here is on the calendar yet.",
        "",
        "Promote a good one by copying it into `data/seed_events.json` with a "
        "verified date/time, then re-run `python build.py`.",
        "",
    ]
    for c in new:
        lines += [
            f"## {c.get('title','(untitled)')}",
            "",
            f"- **Source:** {c.get('source','?')}",
            f"- **Confidence:** {c.get('confidence','?')}",
            f"- **Dates seen:** {', '.join(c.get('dates_raw') or []) or '— none found —'}",
            f"- **Times seen:** {', '.join(c.get('times_raw') or []) or '— none found —'}",
            f"- **Ages seen:** {', '.join(c.get('age_raw') or []) or '— none found —'}",
            f"- **Cost:** {', '.join(c.get('cost_raw') or []) or '—'}",
            f"- **Registration:** {'; '.join(c.get('registration_raw') or []) or '—'}",
            f"- **Link:** {c.get('url','')}",
            "",
            "> Raw text:",
            "",
            "```",
            (c.get("raw_excerpt", "") or "").strip()[:800],
            "```",
            "",
        ]
    REVIEW.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-harvest", action="store_true",
                    help="skip Playwright; re-parse the existing inbox")
    ap.add_argument("--reset-state", action="store_true",
                    help="forget seen fingerprints")
    args = ap.parse_args()

    if args.reset_state and STATE.exists():
        STATE.unlink()
        log("state reset")

    log("=== flyer pass start ===")

    if not args.no_harvest:
        if not run_step("browser_pass.py"):
            # A failed harvest is usually an expired FB session. Say so loudly:
            # silent failure is exactly how the stale-calendar bug hid for weeks.
            log("  ! harvest failed — Facebook session may have expired.")
            log("    Fix:  python browser_pass.py --login")

    if not run_step("flyer.py"):
        log("=== flyer pass end (parse failed) ===")
        return

    # Same cadence, same report: catch seeds whose season ended and source pages
    # whose schedule changed (e.g. a library posting its fall storytime).
    run_step("watch_seeds.py", ["--quiet"])

    if not CANDIDATES.exists():
        log("no candidates file; nothing to review")
        log("=== flyer pass end ===")
        return

    data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    cands = data.get("candidates", [])
    state = load_state()
    seen = state.get("seen", {})

    new = []
    for c in cands:
        fp = fingerprint(c)
        # "none" confidence means no date/time/age was found at all — noise.
        if c.get("confidence") == "none":
            continue
        if fp not in seen:
            new.append(c)
            seen[fp] = {"first_seen": datetime.now().isoformat(timespec="minutes"),
                        "title": c.get("title", "")[:120],
                        "source": c.get("source", "")}

    state["seen"] = seen
    state["last_run"] = datetime.now().isoformat(timespec="minutes")
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    if new:
        write_review(new)
        log(f"** {len(new)} NEW flyer candidate(s) -> {REVIEW}")
        for c in new:
            log(f"     - [{c.get('confidence')}] {c.get('title','')[:70]}")
    else:
        log(f"no new candidates ({len(cands)} known, all seen before)")

    log("=== flyer pass end ===")


if __name__ == "__main__":
    main()
