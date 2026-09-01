import difflib
import os
import tempfile

from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment

load_dotenv()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
CHUNK_DURATION_MS = 20 * 60 * 1000

WINDOW_DURATION_MS = 4 * 1000
WINDOW_OVERLAP_MS = 1500

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


def _make_windows(
    audio: AudioSegment,
    window_duration_ms: int = WINDOW_DURATION_MS,
    window_overlap_ms: int = WINDOW_OVERLAP_MS,
) -> list[tuple[int, AudioSegment]]:
    """Splits audio into overlapping window_duration_ms windows, returned as
    (start_ms, window_audio) pairs. A partial trailing window is always folded
    into the previous one instead of standing alone, since short, mostly-padding
    tail windows are prone to hallucinating unrelated filler content."""
    duration_ms = len(audio)
    if duration_ms <= window_duration_ms:
        return [(0, audio)]

    step_ms = window_duration_ms - window_overlap_ms
    starts = list(range(0, duration_ms, step_ms))

    while len(starts) > 1 and duration_ms - starts[-1] < window_duration_ms:
        starts.pop()

    windows = [
        (start_ms, audio[start_ms : start_ms + window_duration_ms])
        for start_ms in starts[:-1]
    ]
    windows.append((starts[-1], audio[starts[-1] : duration_ms]))
    return windows


def _stitch_transcripts(
    texts: list[str], boundary_chars: int = 80, min_match_chars: int = 6
) -> str:
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
            merged = (
                merged[: len(merged) - len(tail)]
                + tail[: match.a]
                + next_text[match.b :]
            )
        else:
            merged = merged + " " + next_text

    return merged.strip()


def transcribe_full_text(
    filepath: str,
    window_duration_ms: int = WINDOW_DURATION_MS,
    window_overlap_ms: int = WINDOW_OVERLAP_MS,
) -> str:
    if os.path.getsize(filepath) > MAX_UPLOAD_BYTES:
        texts = []
        for _offset_seconds, chunk_path in _iter_audio_chunks(filepath):
            with open(chunk_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="json",
                    language="es",
                )
            texts.append(result.text)
            os.remove(chunk_path)
        return " ".join(texts)

    audio = AudioSegment.from_file(filepath)
    texts = []
    for _start_ms, chunk in _make_windows(audio, window_duration_ms, window_overlap_ms):
        tmp_path = tempfile.mktemp(suffix=".wav")
        chunk.export(tmp_path, format="wav")
        try:
            with open(tmp_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="json",
                )
            texts.append(result.text)
        finally:
            os.remove(tmp_path)

    return _stitch_transcripts(texts)


def transcribe_timestamped_segments(filepath: str) -> list[dict]:
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
