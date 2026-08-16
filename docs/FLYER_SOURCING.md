# Flyer-First / Social-Only Sources — sourcing strategy

**Status:** active playbook · **Added:** 2026-07-28 · **Owner:** KidCal pipeline

This documents a whole *class* of kid-event source that KidCal's normal ingest
(`.ics` feeds, WordPress `?ical=1`, MEC REST) structurally **cannot** see, and
the method for catching it. It was written after a user-flagged miss (below).

---

## 1. The worked example that started this (Rockingham Recreation)

- **Page:** <https://www.facebook.com/p/Rockingham-Recreation-100032044196464/>
  — the recreation department for Bellows Falls / Rockingham, VT (10 Playground
  Rd; Parks & Rec Director Jarrod James, 802-463-9732, recreation@rockbf.org).
- **The event:** a **summer camp**, published as a **two-page flyer** posted to
  the Page's photos, not on any events page:
  - page 1 — `fbid=1659037688507688` (`set=pcb.1659042581840532`)
  - page 2 — `fbid=1659037711841019` (same album)
- **Why the pipeline missed it.** The event does **not** exist as structured
  data anywhere a crawler can reach it:
  - Rockingham Recreation has **no website events page** — every off-site
    reference (town site, chamber, VT 211, Yelp, Trip.com) literally says
    *"visit their Facebook page for schedules and events."*
  - It is **not on a Facebook *Events* page** — it's a **photo post (flyer)**;
    the who/when/cost lives in the **image pixels**, the **post caption**, and
    the **comment thread** (registration details, replies to "how old / how
    much?"), none of which is machine-readable text on a fetchable URL.
  - Every fetch route is gated: WebFetch of the photo URLs redirects to the
    Facebook **login page**; `mbasic.facebook.com` returns *"not available on
    this browser"*; the Page feed truncates. **Confirmed 2026-07-28.**

**Lesson:** for a real subset of the best local kid programming (municipal rec
camps, small community groups), Facebook *is* the system of record, and the
content is a **flyer image + caption + comments**, not an event object.

---

## 2. How to recognize a flyer-first source

Tag a source `type: facebook_flyer` (registry) when **all** hold:

1. Off-site references route you to Facebook ("see our Facebook for the
   schedule") and the org has **no parseable events feed** (no `.ics`, no
   `?ical=1`, no MEC/Eventbrite/LibCal REST).
2. Its programming shows up as **photo posts / flyers** and **post captions**,
   not as Facebook *Event* objects.
3. Load-bearing details (dates, ages, cost, registration) are split across the
   **flyer image + caption + comment replies**.

**Who this catches locally:** municipal **Recreation Departments** and small
community/parent groups. Confirmed instances in radius:
- **Rockingham Recreation** (Bellows Falls, VT) — archetype (bare FB Page).
- **Charlestown Recreation Department** (Charlestown, NH) — bare
  `facebook.com/p/…` Page, no feed; found by applying this strategy.
- **Ludlow VT Parks & Recreation** — candidate via a FB **Group** (harder-gated
  than a Page); a website exists, so verify the structured route first.

**Sweep result (2026-07-28) — most rec depts are NOT flyer-first; they run on
structured platforms.** Re-searching the radius showed true flyer-first is a
*small* set (smallest-budget depts + community groups). The higher-ROI finding:
mid-size towns sit on four recreation platforms, each a reusable adapter that
keeps those towns OUT of the fragile flyer pass. Prefer building these over
flyer-scraping wherever a town has one:

**Two tiers by extractability (probed 2026-07-28):**

**Tier A — clean server-to-server (belongs in the cloud job):** plain GET pages
/ open feeds, no session needed.

| Platform | URL shape | Towns | Status |
|---|---|---|---|
| **MyRec** | `<org>.myrec.com` | Windsor VT, Walpole/Grafton (MA) | **✅ ADAPTER BUILT: `myrec.py`, `type:myrec`.** No .ics (`program_ical.aspx` 404s); schedule is labeled free-text (`Dates:/Days:/Time:/Ages:/Where:/Fee:`) in each `program_details.aspx?ProgramID=` page — plain GET, parseable. Medium-confidence (human-typed). |

**Tier B — browser-session required (a LOCAL Playwright pass, same as the FB
flyers — NOT the cloud job).** These are JS/CSRF/AJAX-hardened: a plain
server-side POST returns only the page shell or an empty payload. **✅ The pass
is built: `browser_pass.py`** (Playwright + Chromium, local, residential IP).

| Platform | URL shape | Towns | Status in `browser_pass.py` |
|---|---|---|---|
| **facebook_flyer** | `facebook.com/…` | Rockingham Rec (BF), Charlestown NH, Ludlow VT | **★ the high-value in-radius target.** Handler harvests flyer images + FB's auto **ALT text** (usually transcribes the flyer's words — no separate OCR) + captions → `data/flyer_inbox/*.txt` for `flyer.py`. Needs a one-time `--login`. |
| **RecDesk** | `<org>.recdesk.com` | *(none in-radius — see note)* | **Handler built & PROVEN** (extracts Program Detail pages: type, Age Min/Max, schedule/times — incl. age-2–5 swim lessons). Server-to-server was blocked (`FilterPrograms` is CSRF-gated; calendar JSON needs a per-org `facilityId`); the browser renders it cleanly. **Note:** `chester.recdesk.com` is Chester **CT**, out of radius — an earlier sweep mis-tagged it as Chester VT (which actually uses chestervt.gov). No confirmed in-radius RecDesk town yet; handler kept as a reusable capability. |
| **SportsEngine / SportNgin** | `<org>.sportngin.com` (or custom domain) | Springfield VT | Low value in-radius: the "calendar" node renders **no events** even in-browser; Springfield's programs are CMS pages + registration forms, all **school-age sport camps** (wrestling/football/basketball/soccer). Not built — revisit only if a town posts preschool programming here. |
| **VSI WebTrac** | `<org>.myvscloud.com/webtrac` | Brattleboro | Registration portal (WebTrac). Not yet built. |

**Running the browser pass (local only):**
```
pip install playwright && python -m playwright install chromium   # one-time
python browser_pass.py --login                 # one-time: log into Facebook (headed)
python browser_pass.py                          # harvest all pass:local FB flyer sources
python browser_pass.py --recdesk https://<org>.recdesk.com   # test the RecDesk handler
```
The FB session lives in `.browser_profile/` and downloaded flyers in
`data/flyer_media/` — both **gitignored** (never pushed). Output flyer text goes
to `data/flyer_inbox/`, which `flyer.py` turns into quarantined candidates.

**Rules of thumb:**
1. **Detect the platform first;** fall back to the flyer pass only when there's
   no feed and no scrapeable page.
2. **Never ship a platform parser written blind** — capture one real non-empty
   sample of the payload first (playbook: validate a feed before trusting it).
   Both Tier-B parsers were *not* shipped precisely because a clean sample
   couldn't be obtained server-to-server.
3. **Tier B = the same Playwright/browser-session pass as the FB flyers.** One
   local logged-in-browser investment unlocks Facebook flyers + RecDesk +
   SportNgin together — build it once, point it at all three.

---

## 3. The harvest method (LOCAL logged-in pass only)

Facebook blocks datacenter IPs and gates content behind login, so this runs in
the **local Playwright pass from a residential IP** (same pass as the rest of
KidCal's FB work) — **never the cloud build**. Registry entries carry
`"pass": "local"` and `build.py` skips them.

For each `facebook_flyer` Page, per run:

1. **Open recent content, not the Events tab.** Load the Page's **Posts** and
   **Photos** tabs (that's where flyers live). Grab the last ~20 posts.
2. **Pull three text layers per candidate post:**
   - **Flyer image → OCR.** Download the photo(s), OCR the pixels
     (tesseract/`pytesseract`, or an image-to-text model from the local
     analysis stack). Multi-page flyers = multiple photos in one album (`pcb.`
     set) — grab the whole album.
   - **Caption text** of the post.
   - **Comment thread** — mine for the *missing* fields (registration link/date,
     age, cost) that people ask about in replies. **Scope: text and
     org/Page/link references only — never profile the individual commenters**
     (KidCal privacy rule).
3. **Merge the three layers** into one candidate event and normalize (title,
   start/end, age, location default, cost, url = the post permalink).
4. **Quarantine, don't auto-publish.** Flyer-derived events are OCR-noisy and
   date-ambiguous → write to `data/flyer_candidates.json` with
   `status: quarantined` + a confidence score for **human review**, then promote
   confirmed ones into `data/seed_events.json`. (Matches the registry's
   quarantine rule for uncertain finds.)
5. **Discovery bonus.** While mining comments/captions, harvest **@-tagged
   Pages, named venues, and outbound links** as *new* candidate sources for the
   registry (orgs/links only).

`flyer.py` is the local skeleton for steps 2b–4: drop raw flyer/caption/comment
text into `data/flyer_inbox/*.txt` (from OCR or manual transcription) and it
emits normalized quarantined candidates. Step 1–2a (Playwright login + image
OCR) is the upstream that fills the inbox.

---

## 3a. API / backdoor investigation (2026-08-16) — what is and isn't reachable

Re-probed every unauthenticated route rather than trusting the 2026-07-28
dead-end list. Result: **one real find, one real dead end, one false lead
corrected.**

### ✅ FOUND: the crawler user-agent bypass

Requesting a Facebook Page with the **`facebookexternalhit/1.1`** user-agent
(Facebook's own link-preview crawler) returns **HTTP 200 with real content and
no login, no cookies, no session**. The same URLs with a normal browser
user-agent return **HTTP 400**. Verified on both in-radius Pages:

| Route | Normal browser UA | `facebookexternalhit` UA |
|---|---|---|
| `facebook.com/profile.php?id=<pageid>` | **400** | **200** — `og:title`, `og:description`, `og:image` |
| `facebook.com/p/<Name-id>/` | 400 | 200 |
| `facebook.com/photo/?fbid=<id>` | 400 | 200 but **empty og:* metadata** |
| `mbasic.` / `m.` / `graph.facebook.com` | 400 | 400 |

**What it actually yields:** Page name, hours, likes, profile image, and the
Page's own blurb. Rockingham Recreation's hours came back cleanly this way.

**What it does NOT yield — the honest limit:** the **post feed is not in the
crawler HTML**. Searching the 489 KB response for `Registration`, `flyer`, or
post captions returns nothing. Individual photo permalinks load but expose
**empty** `og:description`, so flyer captions are not reachable either. The
`plugins/page.php` embed widget returns 200 but renders its timeline via JS, so
it is also empty server-side.

**Verdict:** this is a genuine unauthenticated route into Facebook and worth
keeping for **Page-level metadata and liveness checks** (has this Page gone
dead?). It is **not** a route to flyer content. `browser_pass.py` (local,
logged-in Playwright) remains the only way to reach the flyers themselves.
**No fabrication:** nothing here produced an event, so nothing was added.

### ❌ DEAD END: the town CMS has no recreation content

Chased the better prize — a structured town-hosted source that would retire the
flyer pass entirely. `rockbf.org` is a redirect shell; the real site is
**`rockinghamvt.org`**, running the **MembershipWare** CMS, which exposes a
**completely open, unauthenticated JSON API**:

```
GET https://www.rockinghamvt.org/api/public/mwjsPost?tn=rockinghamvtorg&c=Y&sd=first&et=…&pi=…&eb=…&bo=2
```

It returns `var mwjsMemberData={…}` — strip the `var …=` prefix and parse the
first balanced `{…}` (trailing JS follows the object). Clean structured events:
`PostTitle`, `EventStart`, `EventEnd`, `PostLocation`, `PostDescriptionHtml`.
**55 events, 45 of them future-dated.**

**But every single one is a municipal governance meeting** — Selectboard,
Trustees, Planning Commission, Cemetery Committee, Energy Committee. Zero
recreation programming. The CMS search index confirms it: `recreation`, `camp`,
`youth`, `swim`, `program` all return **0 hits** site-wide.

**Verdict: not a KidCal source.** The API is excellent and the content is
irrelevant. Do not wire it in — it would add 45 selectboard meetings that the
age filter would then have to throw away. Recorded here so nobody re-derives it.

### ⚠️ Correction to the earlier note

The 2026-07-28 note said `mbasic.facebook.com` returns *"not available on this
browser"*. It now returns a hard **HTTP 400** for every UA tried, including the
crawler. The mbasic route is fully gone, not merely degraded.

### Standing conclusion

The three `facebook_flyer` sources stay `pass:local` / `status:quarantined`.
There is no server-to-server backdoor to flyer content. The realistic options
remain: (1) run `browser_pass.py` locally on a residential IP, or (2) the manual
fast-path in §4. For Rockingham specifically, a phone call to **802-463-9732**
still beats every automated route.

---

## 3b. The STANDING pass — scheduled, automatic (2026-08-16)

§3 describes the harvest *method*; this is the part that makes it **recurring
and unattended**. Previously every piece existed but nothing ever ran them, so
flyers only arrived when someone remembered to look. That gap is now closed.

**`flyer_run.py`** is the driver, installed as a **Windows Scheduled Task**
("KidCal Flyer Pass", **Mondays 9:05am**, via `install_flyer_task.ps1`). It
chains:

```
browser_pass.py   harvest FB flyers (Playwright, logged-in, residential IP)
   -> data/flyer_inbox/*.txt
flyer.py          parse -> data/flyer_candidates.json  (quarantined)
watch_seeds.py    expiry + source-page schedule watch
   -> data/flyer_review.md   ONLY the new items, for a 30-second read
```

**Why a Scheduled Task and not GitHub Actions:** Facebook blocks datacenter
IPs. The cloud build skips every `pass:local` source by design, so the recurring
flyer job *must* run on Dan's machine from a residential IP. This is the one
part of KidCal that cannot be moved to the cloud.

**State + quiet runs.** `data/flyer_state.json` fingerprints each candidate
(source + title + dates + times), so an unchanged flyer is reported **once** and
stays silent afterwards. Only genuinely new flyers reach `flyer_review.md`.
Candidates with `confidence: none` (no date, time, or age found) are dropped as
noise.

**Quarantine is NOT relaxed.** Nothing here auto-publishes. `flyer_review.md`
is a human-review queue; promoting an event still means copying it into
`data/seed_events.json` with a verified date. This is the §3 step-4 rule, kept.

**Weekly, not daily,** on purpose: flyer-first orgs post a few times a month,
and low-volume access keeps this unobtrusive. Facebook automated access is a ToS
gray area — keep it personal, local, and low-volume.

**Browser: real Chrome by default (2026-08-16).** `browser_pass.py --browser`
takes `chrome` (default), `chromium` (Playwright's bundled build), or `msedge`.
Real Chrome presents a normal Chrome version/UA to Facebook rather than an
automation build. If the chosen browser can't launch, it falls back to bundled
Chromium automatically — the pass never dies over a browser choice.

⚠ **Each browser gets its OWN profile dir** (`.browser_profile_chrome` vs
`.browser_profile`). Chrome 151 exits immediately if pointed at a profile
written by a different Chromium build, which looks like a mysterious
`TargetClosedError`. Consequence: **switching `--browser` costs one re-login.**
None of these touch your personal Chrome profile — KidCal keeps its own, so your
day-to-day cookies/history are untouched and an open Chrome window doesn't block
the pass.

### 🔴 Chrome will NOT open your personal profile — settled, don't retry

Asked for: drive the real **`Profile 2` / rdanielroth@gmail.com** profile so the
password manager is available. **Chrome blocks this by design.** Tested
2026-08-16 on Chrome 151 with every Chrome window closed:

```
[err] DevTools remote debugging requires a non-default data directory.
      Specify this using --user-data-dir.
```

Chrome refuses to expose the DevTools automation protocol against its **default
User Data directory** — exactly so automation cannot drive a profile holding
saved passwords. **No flag overrides it**, and this is not the profile-lock
problem (it reproduces with Chrome fully closed, `tasklist` showing zero
`chrome.exe`). `--chrome-profile` therefore prints the explanation and exits 2
rather than pretending.

**What `--login` does instead**, which satisfies the underlying need: opens a
**real, headed Chrome** window on KidCal's own profile with
`--disable-extensions` and `--enable-automation` **removed**, so
`navigator.webdriver` is `false` and **password-manager extensions work**. Three
routes to credentials: paste from your manager in another window; install the
manager's extension once (the profile persists, so it's one-time); or let Chrome
save the password. Verified: real Chrome launches, extensions enabled, Facebook
loads.

**One-time setup Dan must do himself** (it needs real credentials):
```
cd C:\Users\User\KidCal
python browser_pass.py --login        # headed real Chrome; log in, press Enter
```
Until that runs, the harvest step fails **loudly** in `data/flyer_run.log` with
the fix command — silent failure is exactly how the stale-calendar bug hid for
25 days.

### `watch_seeds.py` — the staleness alarm

Runs in the same pass. Two checks:

1. **Expiry watch** — any seed whose `RRULE UNTIL` has passed. Caught all four
   Rockingham summer programs that ended 2026-08-15.
2. **Schedule watch** — fingerprints the weekday/time lines on each seed's
   source page. When Rockingham posts its **fall** storytime, the page text
   changes and the next run reports it with the lines it found.

It **reports, never edits.** Seeds are the verified backbone, and a scraped
schedule line is not verification.

---

## 4. Manual fast-path (works today, no automation)

Because the automated FB pass is local/best-effort, the **reliable** path for a
known flyer is: read the flyer, transcribe the text into
`data/flyer_inbox/<slug>.txt`, run `python flyer.py`, review
`data/flyer_candidates.json`, and copy good ones into the seed with a
`"Flyer-sourced; verify with <org>"` note. Cheap, honest, no fabrication.
