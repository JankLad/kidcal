#!/usr/bin/env python3
"""
KidCal — Tier-B browser pass (LOCAL ONLY; never the cloud job).

Some sources can't be read server-to-server — they need a real, JS-rendering
(and sometimes logged-in) browser. This one Playwright harness covers them all
(see docs/FLYER_SOURCING.md §2 "Tier B"):

  * facebook_flyer  — Facebook Pages that publish kids' programming only as
                      photo-post flyers + captions + comments. Needs a one-time
                      login (persisted locally). Harvests flyer images + FB's
                      auto-generated image ALT TEXT (which usually transcribes
                      the flyer's words — no separate OCR needed) + captions
                      into data/flyer_inbox/*.txt for flyer.py.
  * recdesk         — RecDesk (<org>.recdesk.com): programs render via JS and
                      the FilterPrograms POST is CSRF-gated, but a real browser
                      renders /Community/Program with Detail links, and each
                      /Community/Program/Detail?programId= page is cleanly
                      structured (Schedule + Age Min/Max). Proven extractor;
                      kept as a reusable capability (no in-radius RecDesk town
                      confirmed yet — chester.recdesk.com is Chester CT, not VT).

Runs from a residential IP on the user's own machine. Facebook automated access
is a ToS gray area — keep it personal, local, and low-volume.

Requires (local only):  pip install playwright  &&  python -m playwright install chromium

Usage:
  python browser_pass.py --login                 # one-time: log into Facebook
  python browser_pass.py                          # harvest all pass:local FB flyer sources
  python browser_pass.py --source "Rockingham Recreation"
  python browser_pass.py --recdesk https://<org>.recdesk.com   # test the recdesk handler
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / "data" / "sources.json"
INBOX = ROOT / "data" / "flyer_inbox"
MEDIA = ROOT / "data" / "flyer_media"
PROFILE = ROOT / ".browser_profile"          # persisted FB session (gitignored)

FB_HOME = "https://www.facebook.com/"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50]


# --------------------------------------------------------------------------- FB
def _logged_in(page) -> bool:
    # The composer / search only exist when logged in; the login form has #email.
    return page.query_selector("input[name='email']") is None and \
        page.query_selector("[aria-label='Search Facebook'], [aria-label='Facebook']") is not None


def fb_login(context) -> None:
    page = context.new_page()
    page.goto(FB_HOME, wait_until="domcontentloaded", timeout=60000)
    print("A browser window is open. Log into Facebook there.")
    try:
        input("When you see your feed, press Enter here to save the session... ")
    except EOFError:
        page.wait_for_timeout(60000)
    print("Session saved to", PROFILE)
    page.close()


def fb_harvest_page(context, name: str, url: str) -> int:
    """Harvest flyer images + alt text + captions from one FB Page → flyer_inbox."""
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    if not _logged_in(page):
        print(f"  ! not logged in — run:  python browser_pass.py --login")
        page.close()
        return 0
    # Load a chunk of the feed.
    for _ in range(6):
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1500)

    # Flyers are large images; FB's auto ALT text often transcribes their words.
    imgs = page.eval_on_selector_all(
        "img",
        """els => els
            .filter(e => e.naturalWidth > 350 && e.naturalHeight > 350)
            .map(e => ({src: e.currentSrc || e.src, alt: e.getAttribute('alt') || ''}))
        """,
    )
    # Keep the ones whose alt text looks like a flyer (mentions text / an event word).
    kws = re.compile(r"image of text|camp|program|regist|summer|ages?|storytime|"
                     r"kids|children|free|schedule|event", re.I)
    picked, seen = [], set()
    for im in imgs:
        src, alt = im.get("src", ""), im.get("alt", "")
        if not src or src in seen:
            continue
        if "scontent" in src and (kws.search(alt) or len(alt) > 120):
            seen.add(src)
            picked.append(im)

    media_dir = MEDIA / _slug(name)
    media_dir.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(parents=True, exist_ok=True)
    out = INBOX / f"{_slug(name)}.txt"
    lines = [f"SOURCE: name={name} | url={url}", ""]
    for i, im in enumerate(picked, 1):
        alt = re.sub(r"\s+", " ", im["alt"]).strip()
        # download the flyer image for manual/OCR review
        try:
            resp = context.request.get(im["src"], timeout=30000)
            (media_dir / f"flyer-{i:02d}.jpg").write_bytes(resp.body())
        except Exception as e:  # noqa: BLE001
            print(f"    (image {i} download failed: {e})")
        lines.append(f"[flyer {i}] {alt}")
    out.write_text("\n".join(lines), encoding="utf-8")
    page.close()
    print(f"  {name}: {len(picked)} flyer candidate(s) -> {out} (images in {media_dir})")
    return len(picked)


# ----------------------------------------------------------------------- RecDesk
def recdesk_programs(context, base: str) -> list[dict]:
    """Extract kid-relevant RecDesk programs (rendered DOM). Returns raw dicts."""
    base = base.rstrip("/")
    page = context.new_page()
    page.goto(base + "/Community/Program", wait_until="networkidle", timeout=60000)
    cats = page.eval_on_selector_all(
        "a[href*='/Community/Program?category=']",
        "els => els.map(e => [(e.textContent||'').trim(), e.getAttribute('href')])")
    kid_cats = [h for t, h in cats
                if re.search(r"youth|camp|kid|child|swim|afterschool|preschool", t, re.I)]
    ids: dict[str, str] = {}
    for href in kid_cats or ["/Community/Program"]:
        page.goto(base + href, wait_until="networkidle", timeout=60000)
        for h, t in page.eval_on_selector_all(
            "a[href*='/Program/Detail?programId=']",
            "els => els.map(e => [e.getAttribute('href'), (e.textContent||'').trim()])"):
            m = re.search(r"programId=(\d+)", h)
            if m:
                ids[m.group(1)] = t
    out = []
    for pid, title in ids.items():
        page.goto(f"{base}/Community/Program/Detail?programId={pid}",
                  wait_until="networkidle", timeout=60000)
        txt = page.inner_text("body")
        def field(label):
            m = re.search(rf"{label}\s*\t?\s*([^\n]+)", txt, re.I)
            return m.group(1).strip() if m else ""
        amx = re.search(r"Age Minimum[^\n]*\n\s*Maximum\s*\t?\s*([^\n]+)", txt, re.I)
        out.append({
            "programId": pid, "title": title,
            "type": field("Program Type"),
            "age_min": field("Age Minimum"),
            "age_max": amx.group(1).strip() if amx else "",
            "schedule_hint": " ".join(re.findall(
                r"(?i)(?:week of [^.\n]+|\d{1,2}[:/]\d{2}\s*[ap]?m?[^.\n]{0,20})", txt))[:200],
            "url": f"{base}/Community/Program/Detail?programId={pid}",
        })
    page.close()
    return out


# --------------------------------------------------------------------------- main
def main() -> None:
    from playwright.sync_api import sync_playwright  # local-only import

    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="one-time Facebook login")
    ap.add_argument("--source", help="only this source name")
    ap.add_argument("--recdesk", help="test the recdesk handler against a base URL")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    args = ap.parse_args()

    PROFILE.mkdir(exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE), headless=not (args.login or args.headed),
            viewport={"width": 1280, "height": 1600})
        try:
            if args.recdesk:
                for pr in recdesk_programs(context, args.recdesk):
                    print(json.dumps(pr, default=str))
                return
            if args.login:
                fb_login(context)
                return
            sources = json.loads(SOURCES.read_text(encoding="utf-8"))
            fb = [s for s in sources
                  if s.get("type") == "facebook_flyer" and s.get("pass") == "local"
                  and (not args.source or s["name"] == args.source)]
            if not fb:
                print("No matching facebook_flyer sources.")
                return
            total = 0
            for s in fb:
                total += fb_harvest_page(context, s["name"], s["url"])
            print(f"\nHarvested {total} flyer candidate(s) into {INBOX}. "
                  f"Next: python flyer.py")
        finally:
            context.close()


if __name__ == "__main__":
    main()
