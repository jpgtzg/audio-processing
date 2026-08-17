"""Cuts a short slice out of one of the full-hour client_data/Audios Completos
XET-FM recordings and writes it as a wav, for cheap ad-hoc testing of Tool 2
against real station audio without transcribing an entire hour (expensive --
Tool 2 re-transcribes in overlapping windows, so a full hour is hundreds of
Whisper calls).

Usage: uv run python3 -m scripts.slice_sample [start_minutes] [duration_minutes]
"""

import os
import sys

from pydub import AudioSegment

SOURCE = (
    "client_data/Audios Completos XET-FM/"
    "RADIO_MONTERREY-XET-FM_15-07-2026_06-00-00_07-00-00.mp3"
)
OUTPUT_DIR = "client_data/tool2_input"


def main():
    start_min = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    duration_min = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0

    audio = AudioSegment.from_file(SOURCE)
    start_ms = int(start_min * 60 * 1000)
    end_ms = start_ms + int(duration_min * 60 * 1000)
    clip = audio[start_ms:end_ms]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"xetfm_{start_min:.0f}min_{duration_min:.0f}min.wav"
    out_path = os.path.join(OUTPUT_DIR, filename)
    clip.export(out_path, format="wav")
    print(f"Wrote {out_path} ({len(clip) / 1000:.1f}s)")


if __name__ == "__main__":
    main()
