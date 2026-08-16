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

Browser: defaults to real installed Google Chrome (`--browser chrome`), which
looks less automated to Facebook than the bundled Chromium build and carries
Chrome's own version/UA. Falls back to bundled Chromium automatically if Chrome
isn't installed. Use `--browser chromium` to force the bundled build, or
`--browser msedge` for Edge. NOTE: this always uses KidCal's OWN profile
directory (.browser_profile), never your day-to-day Chrome profile — Chrome
refuses to attach to a profile that's already open, and we don't touch your
personal cookies/history.

Usage:
  python browser_pass.py --login                 # one-time: log into Facebook
  python browser_pass.py                          # harvest all pass:local FB flyer sources
  python browser_pass.py --source "Rockingham Recreation"
  python browser_pass.py --browser chromium       # force the bundled build
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


CHROME_USER_DATA = Path(
    r"C:\Users\User\AppData\Local\Google\Chrome\User Data")


def profile_dir(browser: str) -> Path:
    """One profile per browser build.

    A Chrome-created profile and a Chromium-created profile are not
    interchangeable — pointing Chrome 151 at a profile written by the bundled
    Chromium makes it exit immediately. Keeping them separate means switching
    browsers costs one re-login instead of a confusing crash.
    """
    return PROFILE if browser == "chromium" else PROFILE.with_name(
        f".browser_profile_{browser}")


def list_chrome_profiles() -> list[tuple[str, str, str]]:
    """(directory, display name, account) for each real Chrome profile."""
    state = CHROME_USER_DATA / "Local State"
    if not state.exists():
        return []
    try:
        info = json.loads(state.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    cache = (info.get("profile") or {}).get("info_cache") or {}
    return sorted(
        (d, v.get("name", ""), v.get("user_name", "")) for d, v in cache.items()
    )


def resolve_chrome_profile(wanted: str) -> str | None:
    """Match a profile by directory, display name, or account address."""
    w = wanted.strip().lower()
    profiles = list_chrome_profiles()
    for d, name, user in profiles:
        if w in (d.lower(), name.lower(), user.lower()):
            return d
    for d, name, user in profiles:  # fall back to a partial match
        if w and (w in name.lower() or w in user.lower()):
            return d
    return None


def chrome_is_running() -> int:
    """Chrome locks its User Data dir; a running instance blocks automation."""
    import subprocess
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/NH"],
            capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return 0
    return sum(1 for line in out.splitlines() if "chrome.exe" in line.lower())

FB_HOME = "https://www.facebook.com/"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50]


# --------------------------------------------------------------------------- FB
def _logged_in(page) -> bool:
    # The composer / search only exist when logged in; the login form has #email.
    return page.query_selector("input[name='email']") is None and \
        page.query_selector("[aria-label='Search Facebook'], [aria-label='Facebook']") is not None


def fb_login(context, profile: Path) -> None:
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(FB_HOME, wait_until="domcontentloaded", timeout=60000)
    print(
        "\nA real Chrome window is open on KidCal's own profile.\n"
        "  Log into Facebook there.\n\n"
        "  Password manager options (Chrome blocks automation on your personal\n"
        "  profile, so this window starts clean):\n"
        "    * paste from your manager in another window, or\n"
        "    * install your manager's extension here once — extensions are\n"
        "      enabled and the profile persists, so it's a one-time step, or\n"
        "    * let Chrome offer to save the password for next time.\n"
    )
    print(
        "  Expect a two-factor prompt: this is a brand-new browser profile, so\n"
        "  Facebook treats it as a new device. Finish 2FA in the window, and\n"
        "  choose 'Trust this device' / 'Remember browser' if offered — that is\n"
        "  what stops the weekly task from re-prompting.\n"
        "  Ignore the '--no-sandbox / unsupported command-line flag' banner;\n"
        "  it is a normal automation flag and is not the problem.\n"
    )
    try:
        input("When you can see your Facebook FEED (past any 2FA), press Enter... ")
    except EOFError:
        print("(no console input available; waiting 5 minutes)")
        page.wait_for_timeout(300000)

    # Distinguish "never logged in" from "stuck mid-2FA" — they need different fixes.
    url = page.url
    if "two_step_verification" in url or "checkpoint" in url:
        print("\n! Still on Facebook's two-factor / checkpoint step — session NOT saved.")
        print("  Finish the 2FA prompt in the browser window, THEN press Enter.")
        print("  Re-run:  python browser_pass.py --login")
        return
    if page.query_selector("input[name='email']") is not None:
        print("\n! Still showing a login form — the session was NOT saved.")
        print("  Re-run:  python browser_pass.py --login")
        return
    print(f"\nSession saved to {profile}")
    print("The weekly task will reuse it silently. Test it now with:")
    print("    python browser_pass.py")


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
    ap.add_argument("--browser", default="chrome",
                    choices=["chrome", "chromium", "msedge"],
                    help="which browser to drive (default: real Chrome)")
    ap.add_argument("--chrome-profile", metavar="NAME",
                    help="use one of YOUR real Chrome profiles (by folder, "
                         "display name, or email) so your password manager, "
                         "saved logins and extensions are available. "
                         "Requires Chrome to be fully closed.")
    ap.add_argument("--list-profiles", action="store_true",
                    help="show your Chrome profiles and exit")
    ap.add_argument("--check", action="store_true",
                    help="report whether the saved Facebook session is valid")
    args = ap.parse_args()

    if args.list_profiles:
        rows = list_chrome_profiles()
        if not rows:
            print("No Chrome profiles found.")
            return
        print(f"Chrome profiles in {CHROME_USER_DATA}:\n")
        for d, name, user in rows:
            print(f"  {d:<12} {name:<24} {user}")
        print("\nUse:  python browser_pass.py --login --chrome-profile "
              "\"<folder, name, or email>\"")
        return

    # --- real-profile mode: NOT POSSIBLE, by Chrome's design ----------------
    # Chrome refuses DevTools remote debugging against its DEFAULT user-data
    # dir ("DevTools remote debugging requires a non-default data directory"),
    # specifically so automation cannot drive a profile holding saved
    # passwords. No flag overrides it. Verified 2026-08-16 on Chrome 151.
    #
    # So instead of driving the real profile, we make the password manager
    # usable from KidCal's own profile: --login opens a headed window where
    # Chrome's built-in manager still offers to autofill/save, and any
    # extension-based manager can be installed once and persists.
    real_profile: str | None = None
    if args.chrome_profile:
        target = resolve_chrome_profile(args.chrome_profile)
        label = f"{target} ({args.chrome_profile})" if target else args.chrome_profile
        print(
            "\n" + "=" * 72 + "\n"
            f"Chrome will not let automation open your real profile {label}.\n"
            "  \"DevTools remote debugging requires a non-default data directory\"\n"
            "That is a deliberate Chrome protection for saved passwords, not a\n"
            "bug on our side, and no flag disables it.\n\n"
            "What to do instead — you still get a password manager:\n"
            "  1. Run:  python browser_pass.py --login\n"
            "     A REAL headed Chrome window opens on KidCal's own profile.\n"
            "  2. Sign in to Facebook there. To use saved credentials, either:\n"
            "       * open your password manager in another window and paste, or\n"
            "       * install your manager's extension in this window once —\n"
            "         it persists, so this is a one-time step, or\n"
            "       * let Chrome offer to save the login for next time.\n"
            "  3. The session persists; the weekly task reuses it silently.\n"
            + "=" * 72 + "\n"
        )
        sys.exit(2)

    prof = profile_dir(args.browser)
    prof.mkdir(exist_ok=True)
    with sync_playwright() as p:
        # "channel" drives a real installed browser; omitting it uses the
        # bundled Chromium. Real Chrome is the default because it presents a
        # normal Chrome build to Facebook rather than an automation build.
        launch = {
            "headless": not (args.login or args.headed),
            "viewport": {"width": 1280, "height": 1600},
        }
        if args.browser != "chromium":
            launch["channel"] = args.browser

        target = prof
        print(f"  browser: {args.browser}  profile: {prof.name}")

        if args.login:
            # Playwright disables extensions by default, which would block a
            # password-manager extension — the whole point of a headed login.
            # Re-enable them and keep the automation banner off.
            launch["args"] = [
                "--disable-blink-features=AutomationControlled",
            ]
            launch["ignore_default_args"] = [
                "--disable-extensions",
                "--disable-component-extensions-with-background-pages",
                "--enable-automation",
            ]

        try:
            context = p.chromium.launch_persistent_context(str(target), **launch)
        except Exception as e:  # noqa: BLE001 - not installed / profile mismatch
            if args.browser == "chromium":
                raise
            if real_profile:
                # Don't silently fall back to a blank profile — that would drop
                # the password manager the user explicitly asked for.
                sys.exit(
                    f"\nCould not open your Chrome profile {real_profile!r}: "
                    f"{type(e).__name__}\n"
                    f"Almost always a leftover Chrome process holding the lock.\n"
                    f"    Stop-Process -Name chrome -Force\n"
                    f"then re-run the same command.\n"
                )
            print(f"  ! {args.browser} failed to launch ({type(e).__name__}); "
                  f"falling back to bundled Chromium.")
            print(f"    (if {args.browser} is running, its profile may be locked — "
                  f"this uses KidCal's own profile, not your personal one)")
            launch.pop("channel", None)
            fallback = profile_dir("chromium")
            fallback.mkdir(exist_ok=True)
            context = p.chromium.launch_persistent_context(str(fallback), **launch)
        try:
            if args.recdesk:
                for pr in recdesk_programs(context, args.recdesk):
                    print(json.dumps(pr, default=str))
                return
            if args.login:
                fb_login(context, target)
                return
            if args.check:
                page = context.new_page()
                page.goto(FB_HOME, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2500)
                url, ok = page.url, _logged_in(page)
                if ok:
                    print("Facebook session: VALID — the weekly pass can run.")
                elif "two_step_verification" in url or "checkpoint" in url:
                    print("Facebook session: STUCK at 2FA/checkpoint.")
                    print("  Run:  python browser_pass.py --login")
                else:
                    print("Facebook session: NOT logged in.")
                    print("  Run:  python browser_pass.py --login")
                page.close()
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
