# Audio Processing Project — Handoff

> This is the living architecture/technical reference. For "how much is left before we deliver," see `docs/progress.md` instead.

## Client Context

The client operates in media monitoring: they maintain databases of merchants/advertisers plus traditional news/media (radio, open TV). Their core business is recording and extracting commercials, then selling that data — including competitive intelligence — to clients who buy access to the full database. Known commercials are already recognized near-100% via audio fingerprinting (their existing SARA system). The tool shown in the initial meeting is not their identification engine, just a viewer; identification runs on several other tools they already have.

Fingerprinting only works for commercials already in the database. Anything new — or a segment that's probably a commercial but isn't recognized — currently requires manual review to confirm and register. **That manual bottleneck is what Tool 1 automates.**

Full raw notes live in `docs/raw-notes/`. The original scope docs (now superseded by this file and `docs/progress.md`, kept for history) live in `docs/archive/`.

## Scope Decision

Two standalone tools, deliberately decoupled from the client's server/API framing:

- **Tool 1 — active, most-built.** Transcribe already-cropped candidate clips, dedupe repeats, generate a title/label, write the result back onto the source `ALTAS_SARA_FP` row for a capturista to validate as a new commercial.
- **Tool 2 — active, partially built.** Brand-mention detection inside discarded segments (locutor/noticiero/song discards). Was deferred at project start; work began 2026-08-17.

## Requirements changed mid-project — read this before touching Tool 1's code

The original build (`audio.py`, `segmentation.py`, `slicing.py`, `extraction.py`, `tool1.py`) assumed **raw, uncropped audio** as input: it removes silence, transcribes with per-segment timestamps, uses an LLM to detect block boundaries by topic shift, then slices the audio into separate clips. That was correct under the original requirements.

The client has since simplified Tool 1's scope: **the clips are already cropped** by their own SARA pipeline before Tool 1 ever sees them. No boundary detection, no slicing needed. What Tool 1 actually needs to do:

1. Fetch the already-cropped `.wav` for each candidate (currently `client_data/wav2/` locally — see "File access" below).
2. Transcribe with Whisper.
3. Detect spots that repeat more than once (and skip anything already registered in the DB before).
4. Generate a title/label + keywords from the transcript.
5. Write the result somewhere the client's capturista can review and validate it as a new commercial.

The `segmentation.py`/`slicing.py` boundary-detection logic is no longer part of Tool 1's job — it's now redundant with what SARA already does upstream. `audio.py` (Whisper transcription) and `extraction.py` (title/keyword generation) are still relevant and reusable.

## Database access

**Full reference diagram + table-by-table breakdown, published as an artifact:**
**https://claude.ai/code/artifact/cf443bc9-0dce-4fe2-b6e5-d5cef9a31932**

Quick summary — SQL Server `OrbitMedia_Test` (SQL Server 2008). `pymssql` (built on FreeTDS, forcing `tds version = 7.0` via `src/db/freetds.conf`) is what actually connects — modern ODBC drivers fail TLS negotiation against a server this old. `src/db/db.py` wires this up as a SQLAlchemy engine using `.env` credentials (`DB_SERVER_URL`, `DB_SERVER_PORT`, `DB_SERVER_DATABASE`, `DB_LOGIN`, `DB_PASSWORD`, loaded via `src/models/settings.py`).

- **`TESTIGO_SARA`** — 2-hour station recordings. `HOSTNAME` + `ARCHIVO` point at the file on one of ~27 capture PCs (`SARA2`…`SARA40`).
- **`SEGMENTO_SARA`** — segments cut from a testigo. `ID_FP` null = unidentified.
- **`ALTAS_SARA_FP`** — **Tool 1's real entry point, and its write target.** SARA's own new-commercial alta queue.
  **Corrected 2026-08-17** (this reverses what earlier versions of this doc said): Tool 1 reads rows that SARA's own FP recognition pass could **not** identify — i.e. **status 2, "Recortado"** ("recortes pasaron a ser manejados por el programa reconoce los spots como ya identificados y solo deja a los que no se han identificado") — processes them, writes the extracted title/transcript/advertiser back onto that same row, and sets its status to **4, "Validado Img"** so it's surfaced to a capturista (`operario`) for review. Status 4 is Tool 1's *output*, not its input.
  ```sql
  -- input
  SELECT * FROM ALTAS_SARA_FP WHERE ID_ESTATUS_ALTA = 2
  -- Tool 1 processes each row, then:
  -- UPDATE ALTAS_SARA_FP SET ID_ESTATUS_ALTA = 4, ... WHERE ID_ALTAS_SARA_FP = ...
  ```
  The `= 2` input status is a strong inference from the already-confirmed status lifecycle table below, matching the client's description ("grab the ones not identified via FP") — not yet literally confirmed as the number "2" with the client, worth a quick double-check before this goes live. Full status lifecycle (1 Nuevo → 2 Recortado → 4 → 5/7/8/9/10/11) is documented in the artifact.
  This also resolves the previous "Tool 1 write target" open question (#1 below): yes, it writes directly onto the matching `ALTAS_SARA_FP` row, no separate table needed, and reusing status 4 (already meant "surfaced to capturistas") turns out to be exactly the right status to reuse — no new `CAT_ESTATUS_ALTA` value needed after all.
  - `DETALLE` contains the wav's original UNC path, e.g. `\\SARA22\AltasFP\wavs\XHWK_02-08-2026_103021_31.wav` — **this is a reliable exact-match key** against locally-provided wav filenames (see "Matching local wavs to DB rows" below), since the trailing filename is byte-for-byte the same convention used in `client_data/wav2`.
  - `VERSION` is a human-readable auto-label: `<estación> - <fecha DD/MM/YYYY> - <hora HH:MM:SS> - <duración>`.
  - `INICIO` / `DURACION` — **confirmed by ear this session**: `INICIO` is a **millisecond offset directly into the cropped wav file** (not a testigo-relative second offset as originally assumed), and `DURACION` is the real ad's length in **seconds**. So `audio[INICIO_ms : INICIO_ms + DURACION_s*1000]` should isolate just the ad within the padded clip. In practice this is unreliable — see "DB-precise cropping was tried and rejected" below.
  - `ID_SEGMENTO` links back to `SEGMENTO_SARA` if more context is needed.
  - `ID_TIPO_ALTA` is consistently `2` (automated pipeline) for every status-4 row seen so far.

## File access

Files live at `C:\Sara\AltasFp\wav` **locally on whichever `SARA<n>` capture host produced them** — not centralized. Direct `C:\` disk access from the client hasn't landed yet.

**Resolved for Tool 2 (2026-09-03)**: both tools will run on the **SaraAlt** machine, which has network access to every `SARA<n>` capture host's shared folder — confirmed reachable in SaraAlt's Network browser. Per the client, instead of a local path, connect over the network to the corresponding host, e.g. `\\sara3\sara\mp3\<ARCHIVO>` to reach SARA3 (Monterrey). `TESTIGO_SARA.HOSTNAME` gives which `SARA<n>` each testigo belongs to. Wired into `src/tool2.py`'s `resolve_testigo_path()` / `TESTIGO_SHARE_TEMPLATE` — this resolves Tool 2's "real file access" blocker below. The client mentioned SARA3 as a known-good host to test against for now. Tool 1's equivalent (`C:\Sara\AltasFp\wav` access) hasn't been addressed the same way yet — worth confirming whether it's the same SaraAlt UNC pattern (`\\sara<n>\sara\AltasFp\wav`?) or something else.

**Current stand-in**: the client separately shared `client_data/wav2/` — **4,359 already-cropped candidate `.wav` files**, matching the production shape Tool 1 will actually receive (this supersedes the earlier full-day/hour-by-hour audio workaround mentioned in prior versions of this doc). Tool 1's pipeline (`src/tool1.py`) reads directly from this folder.

### Matching local wavs to DB rows

Not every file in `client_data/wav2` has a corresponding DB row (some may be from a different environment/time period than what's in `OrbitMedia_Test`). `scripts/match_wav2_to_db.py` cross-references them:

- Queries `ALTAS_SARA_FP` for rows in the relevant date range with a `.wav]` filename embedded in `DETALLE`, extracts the filename via regex, and intersects it against the local `client_data/wav2` file list.
- **Result: 2,450 of 4,359 local files (~56%) have a matching DB row.**
- Matched files + their DB metadata (`INICIO`, `DURACION`, `OFFSET_INI`, `OFFSET_FIN`, `ID_ALTAS_SARA_FP`, `ID_ESTATUS_ALTA`) get copied into `client_data/real_audio_db/` with a `manifest.csv` — this is the closest thing to a ground-truth set for validating transcription/extraction accuracy against known DB data.

## Stereo dual-emission capture — client confirmed 2026-09-04

Client: "para saber cual es cual en testigo_sara viene un campo que se llama canal viene como 1 o 2 el 1 es el izq y 2 el der." Each file under a `SARA<n>` host's `mp3/` share is not a single station's recording — it's a **stereo capture multiplexing two unrelated station emissions**, one per channel: left (`CANAL=1`) and right (`CANAL=2`). `TESTIGO_SARA.CANAL` says which emission a given row actually is.

Before this was known, `src/tool2.py`'s `crop_segment()` loaded the whole stereo file as-is (and `audio.py`'s `_iter_audio_chunks` large-file branch explicitly did `.set_channels(1)`, downmixing both channels together) — meaning Whisper was being fed **two overlapping, unrelated broadcasts blended into one signal**. This is a very plausible root cause of the garbled/looping transcripts seen when dry-running Tool 2 against fresh data on SaraAlt (2026-09-04): what looked like a Whisper hallucination bug may actually have been Whisper accurately transcribing two stations talking over each other.

**Fixed in `src/tool2.py` (2026-09-04)**: `fetch_discarded_segments()` now also selects `t.CANAL`; `crop_segment()` takes a required `canal` argument and isolates that channel via `pydub`'s `split_to_mono()` before cropping, so only one station's audio ever reaches Whisper. Mirrored in `scripts/tool2_test.py`. Not yet re-validated live against the segment that showed the looping behavior — worth re-running `tool2_test.exe` against the same `ID_SEGMENTO=154650126` to confirm the fix actually cleans up that transcript.

**Open question — does this affect Tool 1 too?** `client_data/wav2` (Tool 1's already-cropped ad clips) come pre-extracted by SARA's own pipeline, not read directly from a raw testigo file by our code — so it's unconfirmed whether SARA already isolates the correct channel before producing those clips, or whether they could carry the same dual-emission problem. Worth asking the client directly before Tool 1's DB-driven file loop is built.

## Missing testigo files — filtered by TESTIGO_SARA.ID_ESTATUS_TESTIGO (client confirmed 2026-09-05)

Dry-running `tool2_test.exe` against fresh `sara3` data repeatedly hit `FileNotFoundError` — every candidate testigo above the scan's lower bound pointed at the same stale 2026-09-03 10:00 batch, and those files are already gone from the live share (see "File access" above; raw mp3 retention is shorter than the DB snapshot's staleness). Separately from that freshness gap, the client flagged that `fetch_discarded_segments()` was never filtering on the parent testigo's own processing status at all — it only checked `SEGMENTO_SARA.ID_ESTATUS_SEGMENTO`, so it could pick up testigos SARA hadn't actually finished processing yet, which are also not reliably present on the share.

**Fixed (2026-09-05)**: `fetch_discarded_segments()` (and `scripts/tool2_test.py`'s equivalent query) now also requires `TESTIGO_SARA.ID_ESTATUS_TESTIGO IN (3, 5)` — "Procesado con Blank" (3) and "Reproceso" (5), the two statuses the client identified as testigos SARA itself considers finished, and therefore actually still on disk. New constants: `TESTIGO_ESTATUS_PROCESADO_CON_BLANK`, `TESTIGO_ESTATUS_REPROCESO`, `TOOL2_TESTIGO_ESTATUS_IDS` in `src/tool2.py`.

## Whisper truncation bug — the main technical problem this session, now fixed

**Symptom**: `whisper-1` sometimes silently stops transcribing partway through a clip — not due to real silence (checked via dBFS), but an internal decoder heuristic ("am I done?") firing prematurely, often around a topic shift, station-ID tag, or music bed. There's no API-exposed parameter to tune this directly on the hosted `whisper-1` endpoint (confirmed via external research, see `docs/transcript_research.md`). Alternative model `gpt-4o-transcribe` was evaluated and rejected — different failure mode (drops other content, non-deterministic, no seed control).

**Fix, implemented in `src/audio.py`**: instead of sending a whole clip as one request, `transcribe_audio()` now:
1. Splits the **whole, untrimmed** clip into overlapping windows (`_make_windows`, `WINDOW_DURATION_MS = 4000`, `WINDOW_OVERLAP_MS = 1500` — tuned down from an initial `7000`/`2500`; smaller windows gave noticeably better results, forcing a fresh Whisper decode more often). Each window is a fresh Whisper request, so an early-stop on one window only costs that window instead of the rest of the file. A partial trailing window is always folded into the previous one (extends it to cover the true end of the clip) rather than standing alone — short/partial tail windows were prone to hallucinating filler content (e.g. "Tokyo, Japan. Tokyo Republic.").
2. Stitches consecutive window transcripts back together with fuzzy character-level matching (`_stitch_transcripts`, via `difflib.SequenceMatcher`) at each boundary, since Whisper doesn't transcribe the same overlapping audio identically between two windows — naive exact-word-match or plain concatenation both failed.

Validated across a ~30-file spot check with mostly clean, accurate, complete results.

**Known accepted limitations** (client decision: leave as-is, not worth the complexity to fix):
- If an ad script genuinely repeats a phrase close together (e.g. "el elevador" twice in one spot), the fuzzy stitcher can occasionally match the wrong occurrence and drop real intervening content.
- Very short/quiet single-window clips can still occasionally hallucinate.

**A real bug fixed this session** (separate from the above): `_make_windows` originally capped every window's end at `start + WINDOW_DURATION_MS`, including the last one. For clips whose duration only barely exceeded one window, the trailing-fold logic could collapse everything down to a single window that didn't reach the clip's actual end — silently dropping the last few seconds before Whisper ever saw them. Fixed by always extending the final window to the clip's true end.

## DB-precise cropping was tried and rejected

Once `client_data/real_audio_db/` existed with real `INICIO`/`DURACION` values, we tried cropping each clip to just the ad (removing padding/other-ad content) before transcribing, instead of running the untrimmed-clip pipeline.

- A helper (`get_spot_crop`) and a crop step in `tool1.py`'s `process()` were built and tested; both have since been **removed** — the untrimmed/windowed approach is what's live in `tool1.py` today.
- **Why it was rejected**: `DURACION` frequently undercuts the real ad length. Tested directly on one file — the DB said the ad was 10s, but the actual ad content (confirmed by progressively widening the crop and re-transcribing) continued to ~18s. Cropping to the DB's stated window cut off real content.
- `scripts/crop_sample.py` still exists as a diagnostic: grabs 5 random files from `client_data/real_audio_db`, crops each to its manifest `INICIO`/`DURACION`, and writes them to `output/{timestamp}/` for a listen-through. Confirmed by ear this session: cropping tight to `DURACION` sounds short/cut off — the untrimmed pipeline is the better source of truth.
- **Takeaway**: `INICIO`/`DURACION` are useful for reference/sanity-checking (e.g. "does this file even have DB backing," roughly where the ad sits), but not reliable enough to use as the actual transcription input.

## What's built so far

| File | Status |
|---|---|
| `src/audio.py` | Whisper transcription with the windowing + fuzzy-stitch fix described above. This is the production transcription path. |
| `src/extraction.py` | Title/keyword generation via LLM — unchanged, still usable. |
| `src/tool1.py` | Reads every `.wav`/`.mp3` in `client_data/wav2`, transcribes (no DB crop, no vocabulary prompt — transcripts are intentionally left "bare" since the windowing fix already improved accuracy without needing steering), extracts spot details, writes results. `main()` currently prints per-file rather than writing a CSV (a prior concurrent/CSV-writing version exists in git history if needed again). |
| `src/db/db.py`, `src/db/base.py` | SQLAlchemy engine + declarative base for DB access, still used by `scripts/` (renamed from `bootstrap/` during a repo cleanup, 2026-08-17). |
| `scripts/match_wav2_to_db.py` | One-off: matches `client_data/wav2` files to `ALTAS_SARA_FP` rows via `DETALLE`, builds `client_data/real_audio_db/` + manifest. |
| `scripts/crop_sample.py` | Diagnostic: random-samples `real_audio_db` crops for manual listening. |
| `scripts/create_mentions_table.py` | Creates Tool 2's output table `MENCIONES_COMERCIALES` — written, not yet run (blocked, see `docs/progress.md`). |

**Removed in a repo cleanup (2026-08-30), all confirmed to have zero remaining callers**: `src/segmentation.py`/`slicing.py` (no longer needed for Tool 1 — clips arrive pre-cropped, already noted above); `scripts/extract_spots.py` (older bootstrap script, superseded by `client_data/wav2`, and had bit-rotted — imported a `SpotDetails` type that no longer existed) plus its now-orphaned `scripts/freetds.conf` copy; `audio.py`'s `remove_silence()` (part of the old boundary-detection pipeline, unused since clips arrive pre-cropped).

## Open questions for the client

1. ~~Write target~~ — **resolved 2026-08-17**, see the `ALTAS_SARA_FP` entry above: writes onto the matching row, reuses status 4.
2. **Dedup logic** — "spots that repeat more than once" needs a concrete matching strategy (audio fingerprint similarity? matching `VERSION`/duration?). `ID_ALTAS_SARA_FP_PADRE` looks like it's meant for parent/duplicate linking but is `NULL` in every sample seen — confirm intended use.
3. **File access scope** — the ~44% of `client_data/wav2` files with no matching DB row: worth asking the client whether that's expected (different environment/date range) or a sign the DB snapshot (`OrbitMedia_Test`) is incomplete relative to the wav set they shared.
4. **`DURACION` accuracy** — worth flagging to the client that `ALTAS_SARA_FP.DURACION` appears to sometimes undercut real ad length; may be worth asking how it's computed upstream, though it's no longer load-bearing for Tool 1 now that cropping isn't used.

## Current access constraints (as of 2026-08-17)

Neither tool has access to the client's **live/production** DB or the actual `SARA<n>` capture machines. Everything built so far runs against `OrbitMedia_Test` (a SQL Server test DB the client set up for this project — see `docs/raw-notes/client-db-messages.md`) plus whatever files the client has separately shared (`client_data/wav2`, etc.). Treat schema/status-code findings from that test DB as reliable for structure, but do not assume the tools can run against real production data yet — that requires access that hasn't landed.

## Tool 2 — now partially scoped

Tool 2 targets `SEGMENTO_SARA` rows discarded (by locutor, noticiero, or song) — not the `ALTAS_SARA_FP` queue Tool 1 uses. Full pipeline detail in the artifact linked above, section 02/05 (note: the artifact predates the confirmations below).

- **Discard catalog table found**: `CAT_ESTATUS_SEGMENTO`, joined via `SEGMENTO_SARA.ID_ESTATUS_SEGMENTO`. Confirmed live against `OrbitMedia_Test`.
- **Client confirmed (2026-08-17)** which discard reasons Tool 2 should cover: **Descartado por Locutor** (`ID_ESTATUS_SEGMENTO = 10`), **Descartado por Noticiero** (`11`), **Descartado por Cancion** (`12`). Wired into `src/tool2.py` as `TOOL2_ESTATUS_IDS`. The "oversized" case discussed earlier in the project isn't required — client confirmed (2026-09-03) it's not part of scope. Still open: `ID_TIPO_SEGMENTO` (a second, separate code on `SEGMENTO_SARA`) doesn't map to anything confirmed yet, but doesn't seem to be needed now that the three discard statuses above cover the request.
- **`fetch_discarded_segments()`** in `src/tool2.py` queries `SEGMENTO_SARA` for those three statuses (tested live — returns 11M+ rows unfiltered against `OrbitMedia_Test`, so it takes an `id_testigo_min` bound). It returns only `ID_SEGMENTO`/`ID_TESTIGO`/`INICIO`/`DURACION` — **no wav file**. Resolving an actual playable clip still needs a join to `TESTIGO_SARA` (for `HOSTNAME`/`ARCHIVO`) plus a crop step, which isn't written yet and is blocked on the file-access gap above.
- Transcription (`transcribe_audio_segments`, reused from Tool 1) and brand-mention extraction (`extract_brand_mentions` in `src/extraction.py`, new) are built and work standalone on any local wav file — just not yet wired to the DB-sourced segments.
- **Output table designed, not yet created**: `scripts/create_mentions_table.py` has the DDL for `MENCIONES_COMERCIALES` (idempotent, safe to re-run) and `src/tool2.py` has `save_mentions()` to insert into it. **Blocked**: the DB login currently in use only has `SELECT` — `CREATE TABLE permission denied in database 'OrbitMedia_Test'` when tried live. Needs either write access granted on this login, or the client running `create_mentions_table.py` (or the DDL inside it) themselves.
- Even once the table exists, `main()`'s local-file test loop still can't call `save_mentions()` — there's no mapping yet from a local wav filename to a real `SEGMENTO_SARA` row (`ID_SEGMENTO`/`ID_TESTIGO`/`ID_ESTATUS_SEGMENTO`), same file-access gap as above. `process()` takes an optional `segment` dict for when that link exists.
