import difflib
import os
import tempfile

from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

load_dotenv()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# The transcription API rejects uploads over 25MB, so oversized files are split into
# fixed-length chunks and re-encoded as low bitrate mp3 (~64kbps mono keeps a chunk
# this long well under the limit regardless of the source format/bitrate).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
CHUNK_DURATION_MS = 20 * 60 * 1000

# Whisper can silently stop transcribing partway through a file when it hits a
# stretch of non-speech mid-clip (e.g. a station-ID tag followed by a music bed
# before a second ad resumes) -- it just returns what it has instead of continuing
# past the gap. Splitting every file into short, overlapping windows forces a fresh
# decode per window, so content after a mid-clip gap doesn't get dropped -- one bad
# "I'm done" decision only costs that window instead of the rest of the file.
# Values tuned empirically: smaller windows (~15s) still let the gap fit inside a
# single window and reproduce the bug; ~7s with ~2.5s overlap reliably surfaced
# content that was previously lost, across a ~30-file spot check.
WINDOW_DURATION_MS = 7 * 1000
WINDOW_OVERLAP_MS = 2500


def remove_silence(
    filepath: str,
    output_path: str | None = None,
    min_silence_len: int = 500,
    silence_thresh_offset: int = 16,
    keep_silence: int = 200,
) -> str:
    """Strips silent stretches (at least `min_silence_len` ms) from the audio,
    keeping `keep_silence` ms of padding around each remaining chunk so words
    aren't clipped. Returns the path to the written file (defaults to
    overwriting a temp copy alongside the original name)."""
    audio = AudioSegment.from_file(filepath)
    silence_thresh = audio.dBFS - silence_thresh_offset

    nonsilent_ranges = detect_nonsilent(
        audio,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh,
    )

    if not nonsilent_ranges:
        trimmed = audio
    else:
        trimmed = AudioSegment.empty()
        for start_ms, end_ms in nonsilent_ranges:
            start_ms = max(0, start_ms - keep_silence)
            end_ms = min(len(audio), end_ms + keep_silence)
            trimmed += audio[start_ms:end_ms]

    if output_path is None:
        base, ext = os.path.splitext(filepath)
        output_path = f"{base}_trimmed{ext or '.wav'}"

    trimmed.export(output_path, format=os.path.splitext(output_path)[1].lstrip(".") or "wav")
    return output_path


def _iter_audio_chunks(filepath: str):
    """Yields (offset_seconds, chunk_filepath) pairs covering the whole file, always
    split into WINDOW_DURATION_MS windows (see comment above) unless the file is
    already shorter than that."""
    if os.path.getsize(filepath) > MAX_UPLOAD_BYTES:
        audio = AudioSegment.from_file(filepath).set_channels(1)
        duration_ms = len(audio)
        for start_ms in range(0, duration_ms, CHUNK_DURATION_MS):
            chunk = audio[start_ms : start_ms + CHUNK_DURATION_MS]
            tmp_path = tempfile.mktemp(suffix=".mp3")
            chunk.export(tmp_path, format="mp3", bitrate="64k")
            yield start_ms / 1000.0, tmp_path
        return

    audio = AudioSegment.from_file(filepath)
    duration_ms = len(audio)
    if duration_ms <= WINDOW_DURATION_MS:
        yield 0.0, filepath
        return

    for start_ms in range(0, duration_ms, WINDOW_DURATION_MS):
        chunk = audio[start_ms : start_ms + WINDOW_DURATION_MS]
        tmp_path = tempfile.mktemp(suffix=".wav")
        chunk.export(tmp_path, format="wav")
        yield start_ms / 1000.0, tmp_path


def _make_windows(audio: AudioSegment) -> list[AudioSegment]:
    """Splits audio into overlapping WINDOW_DURATION_MS windows. A partial trailing
    window is always folded into the previous one instead of standing alone, since
    short, mostly-padding tail windows are prone to hallucinating unrelated filler
    content."""
    duration_ms = len(audio)
    if duration_ms <= WINDOW_DURATION_MS:
        return [audio]

    step_ms = WINDOW_DURATION_MS - WINDOW_OVERLAP_MS
    starts = list(range(0, duration_ms, step_ms))

    while len(starts) > 1 and duration_ms - starts[-1] < WINDOW_DURATION_MS:
        starts.pop()

    return [audio[start_ms : min(start_ms + WINDOW_DURATION_MS, duration_ms)] for start_ms in starts]


def _stitch_transcripts(texts: list[str], boundary_chars: int = 80, min_match_chars: int = 6) -> str:
    """Merges consecutive window transcripts, using a fuzzy character-level match
    near each boundary to find the real overlap (Whisper doesn't transcribe the same
    overlapping audio identically between two windows), instead of naively
    concatenating or requiring an exact word match."""
    if not texts:
        return ""

    merged = texts[0]
    for next_text in texts[1:]:
        if not next_text:
            continue
        if not merged:
            merged = next_text
            continue

        tail = merged[-boundary_chars:]
        head = next_text[:boundary_chars]

        matcher = difflib.SequenceMatcher(None, tail.lower(), head.lower())
        match = matcher.find_longest_match(0, len(tail), 0, len(head))

        if match.size >= min_match_chars:
            merged = merged[: len(merged) - len(tail)] + tail[: match.a] + next_text[match.b :]
        else:
            merged = merged + " " + next_text

    return merged.strip()


def transcribe_audio(filepath: str, prompt: str = "") -> str:
    if os.path.getsize(filepath) > MAX_UPLOAD_BYTES:
        texts = []
        for _offset_seconds, chunk_path in _iter_audio_chunks(filepath):
            with open(chunk_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="json",
                    prompt=prompt,
                )
            texts.append(result.text)
            os.remove(chunk_path)
        return " ".join(texts)

    audio = AudioSegment.from_file(filepath)
    texts = []
    for chunk in _make_windows(audio):
        tmp_path = tempfile.mktemp(suffix=".wav")
        chunk.export(tmp_path, format="wav")
        try:
            with open(tmp_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="json",
                    prompt=prompt,
                )
            texts.append(result.text)
        finally:
            os.remove(tmp_path)

    return _stitch_transcripts(texts)


def transcribe_audio_segments(filepath: str) -> list[dict]:
    segments = []
    for offset_seconds, chunk_path in _iter_audio_chunks(filepath):
        with open(chunk_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        segments.extend(
            {
                "start": segment.start + offset_seconds,
                "end": segment.end + offset_seconds,
                "text": segment.text.strip(),
            }
            for segment in result.segments
        )
        if chunk_path != filepath:
            os.remove(chunk_path)
    return segments
