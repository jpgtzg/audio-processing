# Delivery Progress

Status tracker: what's done, what's blocked, what's left before either tool can go live. For architecture/schema detail, see `docs/handoff.md` — this file is deliberately just the checklist.

**Division of responsibility (confirmed with client, 2026-08-17): the DB/file connection — live production access, `SARA<n>` machine access, write permissions — is a joint effort with the client, not solely on us.** Our deliverable is the processing logic itself (transcription + detection/extraction) working correctly; wiring it to their live infrastructure happens together once they grant the access. So "blocked on DB/file access" below is a shared next step to coordinate, not a red flag on our progress.

**Client has directed: prioritize Tool 2 for deployment first** (their assessment — simpler product surface than Tool 1: no dedup logic, no write-back onto a live operational table). Tool 2's core deliverable — the brand-detection logic — is done and validated; see below.

Last updated: 2026-08-17.

## Tool 1 — new-commercial detection

**Confirmed pipeline (2026-08-17):** read `ALTAS_SARA_FP` rows with `ID_ESTATUS_ALTA = 2` ("Recortado" — SARA's FP recognition already ran and couldn't identify them), process each one, write the extracted title/transcript/advertiser back onto that same row, and set its status to `4` ("Validado Img") so an operario sees it for validation. This resolves the previous "where does Tool 1 write its output" open question — it writes in place, no new table or status needed.

### Done
- Whisper transcription, fixed for the truncation bug (windowed + fuzzy-stitched) — validated against ~30 files, clean and accurate.
- Title/advertiser/category/keyword extraction via LLM (`extract_spot_details`) — working.
- `CATEGORIAS` taxonomy now pulled live from `SUBCAT3.TIT_SUB3` (639 rows) instead of a hardcoded snapshot.
- Local file-based testing pipeline (`src/tool1.py`, reads `client_data/wav2`) — works end-to-end on the client-shared file dump, prints results per file.

### Not yet built
- **The actual DB read/write loop.** `tool1.py` today reads *local files*, not `ALTAS_SARA_FP` rows, and doesn't write anything back. The status-2-in/status-4-out flow above is confirmed with the client but not implemented in code yet.
- **Dedup logic** — "spots that repeat more than once" has no concrete matching strategy defined. `ID_ALTAS_SARA_FP_PADRE` looks intended for this but is `NULL` in every sample seen.

### Blocked
- **DB write access.** Current login is read-only (`CREATE TABLE` was denied when tested for Tool 2 — likely `UPDATE` on `ALTAS_SARA_FP` is blocked too, untested). Needed before the write-back step can run at all.
- **Real file access.** Actual wav files live on `SARA<n>` capture hosts (`C:\Sara\AltasFp\wav`), not centralized; direct access hasn't landed. Currently testing against `client_data/wav2`, a one-time dump the client shared (~56% of it matches a DB row in the test DB).

### Worth confirming with the client
- The `= 2` input status is a strong inference from the already-confirmed status lifecycle (matches "not identified via FP" almost exactly) but hasn't been literally stated as the number "2" — worth a quick sanity check before wiring it into code that writes to their DB.

## Tool 2 — brand-mention detection in discarded segments — **priority for deployment**

Was deferred at project start ("revisit after Tool 1 ships"); work began 2026-08-17, same day as this doc. Client has since asked to prioritize this one first.

### Done
- Discard-reason codes confirmed with the client: `SEGMENTO_SARA.ID_ESTATUS_SEGMENTO` = 10 (Locutor), 11 (Noticiero), 12 (Cancion), via `CAT_ESTATUS_SEGMENTO` (a catalog table that exists, despite earlier notes saying none did).
- `fetch_discarded_segments()` — queries those three statuses, tested live.
- Transcription with per-segment timestamps (`transcribe_audio_segments`, reused from Tool 1) + brand-mention extraction (`extract_brand_mentions`, new) — both work standalone on any local wav file.
- Output table designed: `MENCIONES_COMERCIALES` (title, advertiser, brand, mention start/end, transcript, pending-validation status, linked back to the source segment). Creation script (`scripts/create_mentions_table.py`) and insert function (`save_mentions()`) both written.
- **Tested against real audio (2026-08-17)**: ran the transcription + brand-detection pipeline on a 3-minute slice of `client_data/Audios Completos XET-FM/RADIO_MONTERREY-XET-FM_15-07-2026_06-00-00_07-00-00.mp3` (full-day station audio — not pre-cropped discarded segments, since that linkage doesn't exist yet, but the closest real content available locally; per the client, this folder does still contain actual spots mixed in). Result: correctly found 6 brand mentions clustered in the first 40s (a real ad + station ID), and correctly found zero mentions during the following ~2.5 minutes of pure song — exactly the discrimination Tool 2 needs. Two things worth follow-up: (1) Whisper hallucinated unrelated boilerplate text during the music section (Russian subtitle credits, YouTube captioning artifacts — same known hallucination-on-music behavior already documented for Tool 1); `extract_brand_mentions` correctly ignored it this time, but it's a risk to watch. (2) A single continuous ad/jingle got split into 4 separate "mentions" rather than reported as one — may need prompt tightening if the client wants one row per ad rather than one row per brand-name utterance.

### Done (cont'd)
- **File access resolved (2026-09-03)**: Tool 2 runs on **SaraAlt**, which has network access to every `SARA<n>` capture host's share — client confirmed the path pattern `\\sara<n>\sara\mp3\<ARCHIVO>` (e.g. `\\sara3\sara\mp3\...` for SARA3/Monterrey), keyed by `TESTIGO_SARA.HOSTNAME`. `fetch_discarded_segments()` now joins `TESTIGO_SARA` for `HOSTNAME`/`ARCHIVO`, and `resolve_testigo_path()` builds the UNC path directly — no local mount assumption needed.
- **Confirmed live on SaraAlt (2026-09-03)**: ran `scripts/smoke_test.py` (packaged as `smoke_test.exe` via the new Windows CI build) directly on SaraAlt. Both DB connectivity to `OrbitMedia_Test` and the `\\sara3\sara\mp3` share passed — the share has 29,640 files reachable. This is real confirmation, not just code review; the join-and-crop path Tool 2 was missing is now wired and reachable end-to-end.
- **`ffmpeg` gap found and fixed (2026-09-03)**: SaraAlt initially had no `ffmpeg`/`avconv` on `PATH` (pydub warning surfaced by smoke_test.exe). Installed via `winget install ffmpeg`; a fresh terminal picked it up (`ffmpeg -version` confirmed, warning gone on re-run). `crop_segment()`'s `AudioSegment.from_file()` should now work on SaraAlt.

### Not yet built
- **"Oversized" segment detection** — not a status code, would be a `DURACION` threshold; no value confirmed by the client yet.
- **Segment-offset units** — `crop_segment()` assumes `SEGMENTO_SARA.INICIO`/`DURACION` are seconds (distinct from `ALTAS_SARA_FP`'s millisecond convention); not yet confirmed by ear the way Tool 1's units were.

### Blocked
- **DB write access** — same read-only login issue as Tool 1. `CREATE TABLE MENCIONES_COMERCIALES` was denied live. Table doesn't exist yet because of this.

## Cross-cutting blockers (both tools)

1. **No live/production DB access** — everything runs against `OrbitMedia_Test`, a SQL Server test DB the client set up specifically for this project. Treat schema and status-code findings from it as structurally reliable, but not as production data.
2. **No access to `SARA<n>` capture machines** — resolved for Tool 2 (2026-09-03, see above): running on SaraAlt gives network access to each host's share via `\\sara<n>\sara\mp3\...`. Tool 1 still needs its own equivalent confirmed for `C:\Sara\AltasFp\wav`; until then Tool 1 work is against client-shared file dumps (`client_data/wav2`).
3. **DB login is read-only** — blocks every write-back step both tools need (Tool 1's `UPDATE ALTAS_SARA_FP`, Tool 2's `CREATE TABLE` + `INSERT`).

## Suggested next asks for the client

- Grant write access (or confirm who can run `scripts/create_mentions_table.py`) on `OrbitMedia_Test`.
- Confirm Tool 1's input status is literally `2` (Recortado).
- Confirm a `DURACION` threshold for "oversized" segments (Tool 2).
- Timeline for live DB / `SARA<n>` file access, since both tools are currently unverifiable against real production data without it.
