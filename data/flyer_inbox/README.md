# flyer_inbox — raw flyer text drop for `flyer.py`

One `.txt` per flyer, from OCR (local Playwright pass) or manual transcription.
`python flyer.py` parses these into `data/flyer_candidates.json` (quarantined,
for human review). See `docs/FLYER_SOURCING.md`.

**Filename:** `<source-slug>.txt` (the stem becomes the source name if no header).

**Optional first line** carries metadata; everything after it is the flyer text:

```
SOURCE: name=Rockingham Recreation | location=10 Playground Rd, Bellows Falls, VT | url=https://www.facebook.com/p/Rockingham-Recreation-100032044196464/
<flyer image OCR text>
<post caption>
<relevant comment-thread replies — details only, no commenter names>
```

`flyer.py` best-effort extracts dates/times/ages/cost/registration/links and
scores confidence. Output is **never** auto-published — review, then copy
confirmed events into `data/seed_events.json` with a "Flyer-sourced; verify"
note. Nothing real lives in this folder by default (transient working dir).
