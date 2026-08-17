> **Archived.** This was the original scope doc — kept for history. It's superseded by `docs/handoff.md` (current architecture) and `docs/progress.md` (current status). Notably outdated: Tool 1 here still describes trimming/boundary-detection, which the client later removed from scope (clips arrive pre-cropped).

# Audio Processing Project — Requirements

## Client Context

The client operates in media monitoring: they maintain databases of merchants/advertisers plus traditional news/media (radio, open TV). Their core business is recording and extracting commercials, then selling that data — including competitive intelligence — to clients who buy access to the full database. Known commercials are already recognized near-100% via audio fingerprinting. The system shown in the initial meeting is not their identification engine — it's only a viewer; identification runs on several other tools.

The client has already floated the idea of using ChatGPT/AI for part of this process.

## Problem Statement

Fingerprinting only works for commercials already in the database. Anything new — or unidentified segments that are probably commercials — currently requires manual audio trimming to locate start/end points. This is the bottleneck they want automated.

## Proposed Solution — Two Tools

Input audio is a given for both tools — the client's server provides it (via API or DB, doesn't matter which). The focus here is the tools themselves, not the hand-off mechanics.

**Tool 1: Clip Trimming, Transcription & Naming**
- Input: a single audio clip that fingerprinting failed to identify
- Trim the clip to the commercial's actual start/end boundaries (replacing today's manual trimming)
- Transcribe the trimmed clip using Whisper
- Generate keywords and a name/label for the clip
- Store the result (destination/schema TBD)

**Tool 2: Stream Sponsored-Segment Detection & Extraction**
- Input: the full radio/TV transmission (continuous program audio, not a pre-isolated clip)
- Remove music/songs from the recording
- Keep only host/commentator/announcer speech
- Within that speech, detect sponsored sections that "appear out of nowhere" — applies to both brand mentions and sponsored content embedded in news
- Transcribe the detected sections using Whisper
- Extract keywords — scope still open: brand/company names only, or news topics too (needs client confirmation)
- Store the result (destination/schema TBD)

## Functional Requirements

| # | Requirement |
|---|---|
| 1 | Trim an unidentified clip to the commercial's actual start/end boundaries (Tool 1) |
| 2 | Transcribe the trimmed clip with Whisper (Tool 1) |
| 3 | Generate keywords and a name/label for the clip (Tool 1) |
| 4 | Remove music/songs from stream audio, keeping only host/commentator speech (Tool 2) |
| 5 | Detect sponsored sections within that speech, for both brands and news content (Tool 2) |
| 6 | Transcribe detected sponsored sections with Whisper (Tool 2) |
| 7 | Extract keywords from those sections — scope (brands only vs. brands + news topics) TBD (Tool 2) |

## Non-Functional / Product Requirements

- Database: SQL Server is a hard constraint
- Client integration (how audio arrives, service/dashboard framing, etc.) is deprioritized for now — current focus is building Tool 1 and Tool 2 so they work correctly in isolation

## Open Questions Worth Clarifying with the Client

- Tool 2 keyword scope: brand/company names only, or news topics too?
- Where/how should results be stored (schema TBD for both tools)?
- Any labeled examples of "almost certainly a commercial but unidentified" clips, to calibrate Tool 1's boundary-detection?
- Any labeled examples of sponsored sections "appearing out of nowhere," to calibrate Tool 2's detection?
