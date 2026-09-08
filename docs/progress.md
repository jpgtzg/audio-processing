# Delivery Progress

Status tracker: what's done, what's blocked, what's left before either tool can go live. For architecture/schema detail, see `docs/handoff.md` — this file is deliberately just the checklist.

**Division of responsibility (confirmed with client, 2026-08-17): the DB/file connection — live production access, `SARA<n>` machine access, write permissions — is a joint effort with the client, not solely on us.** Our deliverable is the processing logic itself (transcription + detection/extraction) working correctly; wiring it to their live infrastructure happens together once they grant the access. So "blocked on DB/file access" below is a shared next step to coordinate, not a red flag on our progress.

**Client has directed: prioritize Tool 2 for deployment first** (their assessment — simpler product surface than Tool 1: no dedup logic, no write-back onto a live operational table). Tool 2's core deliverable — the brand-detection logic — is done and validated, and it now runs as a self-resuming hourly service rather than a one-off script; see below. The main thing left blocking a fully hands-off live demo is `SARA3` data freshness on the client's side (see "Blocked (new)" under Tool 2).

Last updated: 2026-09-05.

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
- **Path-resolution bug found and fixed (2026-09-03)**: `TESTIGO_SARA.ARCHIVO` values already embed their own subfolder (e.g. `MP3\XHRED-XHM_06-08-26_100000.MP3` — confirmed across 10 sampled SARA3 rows), but `resolve_testigo_path()` was appending `ARCHIVO` onto `\\<host>\sara\mp3`, doubling the `mp3` segment (`\\sara3\sara\mp3\MP3\...`) into a path that doesn't exist. `TESTIGO_SHARE_TEMPLATE` now points at the share root (`\\<host>\sara`) and lets `ARCHIVO` supply the rest — real path is `\\sara3\sara\MP3\<file>`. Caught before it was ever run against real segments; not yet re-verified live (see `scripts/tool2_test.py` below).
- **Read-only dry-run tool added**: `scripts/tool2_test.py` (built as `tool2_test.exe` via CI) pulls up to 10 discarded segments for one host (default SARA3), runs the same crop → transcribe → brand-detection pipeline as `src/tool2.py`, and writes results to a `.txt` file. Never calls `save_mentions()` — safe to run before `MENCIONES_COMERCIALES` exists.
- **Ran live on SaraAlt against 10 distinct SARA3 recordings (2026-09-03): 10/10 not found on the live share**, under both the current path construction and the pre-fix one (`diagnose_missing_file()` checked both). Since the miss is 100% across a diverse file sample — not clustered on one recording — this points at the `OrbitMedia_Test` snapshot being stale (frozen 2026-08-06, ~1 month old) rather than a path bug: the DB rows reference recordings that have since rotated/been deleted off the live SARA3 share. Path resolution itself is not confirmed working end-to-end yet, since no real file has been successfully reached this way.

### Blocked (new) — partially resolved, one host still stuck
- **`OrbitMedia_Test` snapshot refreshed by the client (2026-09-04)**, unblocking most of the validation work below — `TESTIGO_SARA`/`SEGMENTO_SARA` now reach 2026-09-03 for most hosts. **`SARA3` specifically never advanced past 2026-09-03 10:00**, though, and by 2026-09-05 those files had already rotated off the live share (confirmed both via `FileNotFoundError` and by checking `MAX(FECHA_INICIO)` for that host directly) — so `SARA3` dry runs still reliably hit missing files. Asked the client for another refresh specifically covering `SARA3`, plus how long raw `mp3` captures are actually retained on the live shares (that number determines how fresh any snapshot needs to stay for Tool 2 to find real files at all).

### Done (cont'd) — stereo dual-emission fix, testigo-status filter, service loop (2026-09-04/05)
- **Stereo dual-emission bug found and fixed (2026-09-04)**: client confirmed each file under a `SARA<n>` host's `mp3/` share is actually a stereo capture multiplexing **two unrelated station emissions**, one per channel (`TESTIGO_SARA.CANAL`, 1=left/2=right) — not a single station's recording as previously assumed. Before this was known, `crop_segment()` fed the whole blended stereo mix to Whisper, which explains the severely garbled/looping transcripts seen in earlier dry runs. Fixed: `crop_segment()` now requires a `canal` argument and isolates that channel via `pydub` before cropping. Validated both locally (against a real copy of the previously-broken file) and live on SaraAlt — same segment now produces one clean, coherent, non-looping transcript.
- **`ID_ESTATUS_TESTIGO` filter added (2026-09-05, client-requested)**: `fetch_discarded_segments()` now also requires the parent testigo's `ID_ESTATUS_TESTIGO IN (3, 5)` — "Procesado con Blank"/"Reproceso", the statuses the client identified as testigos SARA itself considers finished (and therefore actually present on the live share). Segments from testigos SARA hadn't finished processing yet were a separate source of `FileNotFoundError`, distinct from the stale-snapshot issue above.
- **Tool 2 now runs as a self-resuming service, not a one-off script (2026-09-05)**: `python -m src.tool2` (no args) polls hourly, tracking the last-processed `ID_TESTIGO` in a local state file that auto-seeds from the live `MAX(ID_TESTIGO)` on first run — no manual seeding or external scheduler (e.g. Windows Task Scheduler) needed, since this deploys as a standing service. A one-off `python -m src.tool2 <id_testigo_min>` backfill/dry-run mode still exists separately.
- **`tool2_test.exe` now supports multiple/all hosts (2026-09-05)**: was hardcoded to one host (`sara3`) for manageable dry runs; now takes a comma-separated list or `all`, matching `src/tool2.py`'s real production scope (which has no host filter at all).
- **First real `MENCIONES_COMERCIALES` writes reviewed and were all false positives (2026-09-05)**: two causes — known Whisper hallucination stock phrases (e.g. `www.alimmenta.com`, "Subtítulos realizados por la comunidad de Amara.org") showing up regardless of actual audio content, and station self-promotion the extraction prompt didn't yet catch (a station's own app, its own ad-sales product, its own frequency). Prompt hardened with an explicit hallucination-artifact exclusion and a first-person-possessive heuristic for self-promotion; re-verified against the actual transcripts that produced all 9 bad rows, all now correctly return zero mentions. Bad rows deleted after the fix was confirmed.
- **`MOTIVO_DESCARTE` column added to `MENCIONES_COMERCIALES` (2026-09-05, client-requested)**: human-readable discard reason (`LOCUTOR`/`NOTICIERO`/`CANCION`), populated automatically by `save_mentions()` so it's readable without joining back to `SEGMENTO_SARA`/`CAT_ESTATUS_SEGMENTO`. Migration in `scripts/create_mentions_table.py` handles both a fresh table and one that predates this column.

### Not yet built
- **Segment-offset units** — `crop_segment()` assumes `SEGMENTO_SARA.INICIO`/`DURACION` are seconds (distinct from `ALTAS_SARA_FP`'s millisecond convention); not yet confirmed by ear the way Tool 1's units were.
- **Windowing for Tool 2's transcription path** — `transcribe_timestamped_segments()` (Tool 2) doesn't have the windowing/fuzzy-stitch fix `transcribe_full_text()` (Tool 1) has for long unwindowed clips; proposed but not implemented, and possibly moot now that the stereo-channel fix has cleaned up transcript quality significantly.
- Whether Tool 1's `client_data/wav2` clips (pre-cropped by SARA's own pipeline, not read directly from a raw testigo file by our code) could carry the same dual-emission problem is unconfirmed — worth asking the client before Tool 1's DB-driven file loop is built.

### DB write access — resolved (2026-09-03), then wiped and re-resolved (2026-09-05)
Client confirmed write access is now granted. Verified directly (not just re-tried the old blocked path): `MENCIONES_COMERCIALES` already exists live in `OrbitMedia_Test` with exactly the designed schema (`scripts/create_mentions_table.py` reported "already exists, skipping" — someone, likely the client, created it since the client granted access). Ran `save_mentions()` with a throwaway test row (`ID_SEGMENTO=-1`) — insert succeeded with all fields (`TITULO`/`ANUNCIANTE`/`MARCA`/mention timestamps/transcript/default `ID_ESTATUS_VALIDACION=1`) landing correctly, then deleted it.

**The 2026-09-04 `OrbitMedia_Test` snapshot refresh wiped `MENCIONES_COMERCIALES` along with `CREATE TABLE` permission** — both had to be re-established on 2026-09-05 (permission came back on its own; the table was simply recreated via `scripts/create_mentions_table.py`, which is idempotent). Worth flagging to the client that any future snapshot refresh will likely repeat this, since it looks like a schema restore rather than an incremental update. **The full pipeline including the DB write-back is now confirmed working end-to-end against real segments**, not just designed — see the false-positive review above for what shipped first and how it was corrected.

## Cross-cutting blockers (both tools)

1. **No live/production DB access** — everything runs against `OrbitMedia_Test`, a SQL Server test DB the client set up specifically for this project. Treat schema and status-code findings from it as structurally reliable, but not as production data.
2. **No access to `SARA<n>` capture machines** — resolved for Tool 2 (2026-09-03, see above): running on SaraAlt gives network access to each host's share via `\\sara<n>\sara\mp3\...`. Tool 1 still needs its own equivalent confirmed for `C:\Sara\AltasFp\wav`; until then Tool 1 work is against client-shared file dumps (`client_data/wav2`).
3. **DB login is read-only** — blocks every write-back step both tools need (Tool 1's `UPDATE ALTAS_SARA_FP`, Tool 2's `CREATE TABLE` + `INSERT`).

## Suggested next asks for the client

- Confirm Tool 1's input status is literally `2` (Recortado).
- Refresh `SARA3`'s data specifically in `OrbitMedia_Test` (or grant live DB access) — every other host advanced with the 2026-09-04 refresh, but `SARA3` (the host used for testing so far) is still stuck at 2026-09-03 10:00, and those files have already rotated off the live share.
- How long are raw `mp3` captures actually retained on the live `SARA<n>` shares before rotation/deletion? Determines how fresh any `OrbitMedia_Test` snapshot needs to stay for Tool 2 to reliably find real files.
- Heads-up: expect `MENCIONES_COMERCIALES` (and `CREATE TABLE` permission) to get wiped again on any future full snapshot refresh, same as happened 2026-09-04 → 2026-09-05 — it looks like a schema restore, not an incremental update. `scripts/create_mentions_table.py` recreates it in one command if that happens again.
