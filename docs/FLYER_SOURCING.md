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

## 4. Manual fast-path (works today, no automation)

Because the automated FB pass is local/best-effort, the **reliable** path for a
known flyer is: read the flyer, transcribe the text into
`data/flyer_inbox/<slug>.txt`, run `python flyer.py`, review
`data/flyer_candidates.json`, and copy good ones into the seed with a
`"Flyer-sourced; verify with <org>"` note. Cheap, honest, no fabrication.
