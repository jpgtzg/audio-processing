import os
import tempfile

from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

load_dotenv()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# The transcription API rejects uploads over 25MB. Files under that just get sent
# as-is; larger ones are split into fixed-length chunks and re-encoded as low
# bitrate mp3 (~64kbps mono keeps a chunk this long well under the limit
# regardless of the source format/bitrate) before being sent one at a time.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
CHUNK_DURATION_MS = 20 * 60 * 1000


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
    """Yields (offset_seconds, chunk_filepath) pairs covering the whole file.
    For files already under the upload limit, yields the original file once."""
    if os.path.getsize(filepath) <= MAX_UPLOAD_BYTES:
        yield 0.0, filepath
        return

    audio = AudioSegment.from_file(filepath).set_channels(1)
    duration_ms = len(audio)
    for start_ms in range(0, duration_ms, CHUNK_DURATION_MS):
        chunk = audio[start_ms : start_ms + CHUNK_DURATION_MS]
        tmp_path = tempfile.mktemp(suffix=".mp3")
        chunk.export(tmp_path, format="mp3", bitrate="64k")
        yield start_ms / 1000.0, tmp_path


def transcribe_audio(filepath: str) -> str:
    texts = []
    for offset_seconds, chunk_path in _iter_audio_chunks(filepath):
        with open(chunk_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="json",
            )
        texts.append(result.text)
        if chunk_path != filepath:
            os.remove(chunk_path)
    return " ".join(texts)


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
