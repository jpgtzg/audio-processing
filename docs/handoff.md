# Audio Processing Project — Handoff

## Client Context

The client operates in media monitoring: they maintain databases of merchants/advertisers plus traditional news/media (radio, open TV). Their core business is recording and extracting commercials, then selling that data — including competitive intelligence — to clients who buy access to the full database. Known commercials are already recognized near-100% via audio fingerprinting. The tool shown in the initial meeting is not their identification engine, just a viewer; identification runs on several other tools they already have.

The client has floated using ChatGPT/AI for part of this process. Fingerprinting only works for commercials already in the database — anything new, or unidentified segments that are probably commercials, currently requires manual audio trimming to find start/end points. That manual bottleneck is what this project automates.

Full raw notes and original requirements synthesis live in `initial-metting-notes` and `requirements.md`.

## Scope Decision

We're building **two standalone tools**, deliberately decoupled from how the client's server hands off audio (API vs. DB — doesn't matter for tool design) and from the "service" framing (dashboard/API/alerts) raised in the initial meeting. Those integration questions are real but deprioritized until the tools themselves work.

**Tool 1 — Clip Trimming, Transcription & Naming**
Input: audio containing one or more commercials/announcements that fingerprinting failed to identify. Trim to actual boundaries, transcribe with Whisper, generate keywords + a name/label per clip, store the result (destination/schema still TBD).

**Tool 2 — Stream Sponsored-Segment Detection & Extraction** *(not started)*
Input: the full radio/TV transmission (continuous program audio, not a pre-isolated clip). Strip music/songs, keep only host/commentator speech, detect sponsored sections that "appear out of nowhere" within that speech (applies to both brand mentions and sponsored content embedded in news), transcribe those sections, extract keywords, store.

Both tools share a spine — audio → isolate speech worth caring about → Whisper transcribe → extract/match → store — but the "isolate" step differs enough (bounded-segment trim vs. continuous stream filtering) to justify building them as separate pipelines with shared components.

## What We've Built (Tool 1)

Working end-to-end pipeline, tested against `input/audio1.wav` and `input/audio2.wav`:

| File | Role |
|---|---|
| `audio.py` | Whisper transcription. `transcribe_audio` returns plain text; `transcribe_audio_segments` returns segment-level `{start, end, text}` timestamps — needed for boundary detection. |
| `segmentation.py` | `detect_blocks` — sends the segment list to an LLM (gpt-4.1-mini), which groups segments into distinct commercial/content blocks wherever the topic clearly shifts, returning `{start, end, text}` per block. This is the boundary-detection step, done via topic grouping rather than silence detection, because real content often has no silence gap between spots. |
| `slicing.py` | `slice_audio` — uses `pydub` (+ `audioop-lts`, needed as a backport since Python 3.13 dropped stdlib `audioop`) to cut the original `.wav` at block boundaries and export one file per block into `output_blocks/`. |
| `extraction.py` | `extract_keywords_and_name` — LLM call (gpt-4.1-mini) that reads a block's transcript and returns `{keywords, name}` as structured JSON. Output is forced to Spanish (brand names kept verbatim). Handles empty/garbled transcripts by returning `"Clip no identificado"` instead of hallucinating a brand. |
| `main.py` | Orchestrates the full pipeline per file in `input/`: transcribe segments → detect blocks → slice audio → per block, extract keywords/name → write everything to `output.txt`. |

**Dependencies added:** `openai`, `python-dotenv`, `pydub`, `audioop-lts`. `OPENAI_API_KEY` loads from `.env` (gitignored) via `python-dotenv`.

**Storage:** currently stubbed as local files (`output_blocks/*.wav` + `output.txt`) — no DB wiring yet. SQL Server is a hard constraint from the client but schema/destination is still an open question.

### Validation so far

`audio2.wav` (a ~6 min radio segment) was correctly split into 14 distinct blocks — station jingles, a water-safety PSA, a jobs announcement, a human rights program spot, several show promos, a sports/ticket ad, a literacy campaign spot, a Congress equality spot, and an infrastructure ad — each cut into its own `.wav` with an accurate name and keyword list. Notably:
- The topic-grouping approach correctly separated blocks that ran directly into each other with **no silence gap**, which a pure silence-detection approach would have missed.
- A jingle-only block (no commercial content) was correctly labeled `Clip no identificado` with empty keywords instead of a hallucinated brand.

## What's Next

**Hardening Tool 1** (not yet done):
- Spot-check the actual sliced audio (not just transcript boundaries) to confirm cuts aren't clipping words at block edges.
- Test against messier input — this sample was clean/back-to-back; real unidentified clips from the client may have overlapping speech/music or more ambiguous transitions.
- Check cost/latency at realistic volume — current pipeline does 1 Whisper transcription + 2 LLM calls (segmentation, then extraction per block) per input file.

**Tool 2** — not started. Needs a speech-vs-music filter (keep only host/commentator audio) and a sponsored-section detector within that filtered stream, distinct from Tool 1's bounded-clip trimming.

**Open questions still outstanding** (see `requirements.md`):
- Tool 2 keyword scope: brand/company names only, or news topics too? (needs client confirmation)
- Where/how should results be stored — schema TBD for both tools, SQL Server is the hard constraint.
- Labeled examples from the client for both boundary-detection (Tool 1) and sponsored-section detection (Tool 2), to calibrate against real cases rather than just the two sample files we have.

**Deliberately deferred:** client integration mechanics (how audio actually arrives), and the "service" framing (dashboard/API/alerts) — revisit once both tools work reliably in isolation.
