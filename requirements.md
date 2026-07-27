# Audio Processing Project — Requirements

## Client Context

The client operates in media monitoring: they maintain databases of merchants/advertisers plus traditional news/media (radio, open TV). Their core business is recording and extracting commercials, then selling that data — including competitive intelligence — to clients who buy access to the full database. Known commercials are already recognized near-100% via audio fingerprinting. The system shown in the initial meeting is not their identification engine — it's only a viewer; identification runs on several other tools.

The client has already floated the idea of using ChatGPT/AI for part of this process.

## Problem Statement

Fingerprinting only works for commercials already in the database. Anything new — or unidentified segments that are probably commercials — currently requires manual audio trimming to locate start/end points. This is the bottleneck they want automated.

## Proposed Solution — Two Processes

**1. Transcription & Extraction (Whisper)**
- Transcribe audio using Whisper
- Extract keywords, brand mentions, and commercial-related entities
- Focus only on announcer/newscaster speech — filter out music/songs and already-identified commercials
- Feed extracted keywords/brands into the database

**2. Unidentified Segment Detection & Classification**
- Detect sponsored mentions/segments that "appear out of nowhere" (for both brands and news content)
- Automatically determine start/end boundaries of these segments (replacing manual trimming)
- Transcribe the segment
- Cross-reference against the existing brand database to preventively classify which brand/advertiser it belongs to

## Functional Requirements

| # | Requirement |
|---|---|
| 1 | Ingest audio automatically (existing server already streams/sends audio) |
| 2 | Auto-detect start/end of unidentified segments likely to be commercials |
| 3 | Transcribe audio (Whisper) to generate searchable keywords |
| 4 | Filter out music and already-fingerprinted commercials — process only spoken/announcer content |
| 5 | Match transcribed content against brand database to classify the commercial |
| 6 | Store sentence-level start/end timestamps alongside transcriptions |
| 7 | Insert extracted keywords/brands/commercial elements into the database |

## Non-Functional / Product Requirements

- Framed as a service, not just a batch tool — needs visibility into what has already been recognized vs. what's still pending/unidentified
- Database: SQL Server is a hard constraint
- Must integrate with their existing auto-listening server pipeline — this new component only needs to handle new/unrecognized commercials (trim → transcribe → classify)

## Open Questions Worth Clarifying with the Client

- What format/API does the existing server use to hand off audio to this new component?
- What does the current brand database schema look like (for matching/classification)?
- Any labeled examples of "almost certainly a commercial but unidentified" segments to calibrate the boundary-detection model?
- Expected volume/latency requirements (real-time vs. batch)?
- What does "service" mean concretely to them — a dashboard, an API, alerts?
