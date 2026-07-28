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
- **Rockingham Recreation** (Bellows Falls, VT) — archetype.
- **Charlestown Recreation Department** (Charlestown, NH) — bare
  `facebook.com/p/…` Page, no feed; found by applying this strategy.
- Candidates to check next: Springfield (VT) Rec, Walpole (NH) Rec (has a town
  `.us` site *and* an FB page — check both), church/library "story time" flyers.

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
