"""Benchmarks self-hosted faster-whisper against real Tool 2 segments.

Run this on the machine with real production DB access and a network path to
the \\\\sara<n>\\ shares (this dev sandbox has neither -- .env here points at
OrbitMedia_Test, which is missing EMISORAS_MENCION, and there's no route to
the capture-host shares). Needs a .env with real DB_* credentials pointed at
production, same as run_tool2.py.

Uses the real src.tool2.queries.fetch_discarded_segments() -- now that
usp_Tool2_FetchDiscardedSegments/usp_Tool2_InsertMencionComercial are both
deployed (see docs/progress.md) -- so this stays in sync with the actual
pipeline instead of duplicating the query.

For each fetched segment: crops it exactly like the real pipeline
(src.tool2.crop.crop_segment), transcribes it locally with faster-whisper,
timing wall-clock duration against the clip's own length (real-time factor:
below 1.0 = faster than the audio plays), and prints the transcript so you
can eyeball quality against what whisper-1 would have produced.

Usage:
    uv run scripts/bench_local_whisper.py [--limit N] [--model small|medium|large-v3] [--lookback N] [--id-min ID]
"""

import argparse
import os
import time

from src.tool2.crop import crop_segment
from src.tool2.queries import current_max_id_segmento, fetch_discarded_segments


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=2, help="how many segments to benchmark")
    parser.add_argument(
        "--lookback",
        type=int,
        default=20000,
        help="scan this many ID_SEGMENTO back from the current max to find --limit matching rows",
    )
    parser.add_argument(
        "--id-min",
        type=int,
        default=None,
        help="fetch from this ID_SEGMENTO and benchmark the first --limit rows (overrides --lookback)",
    )
    parser.add_argument(
        "--model", default="small", choices=["tiny", "base", "small", "medium", "large-v3"]
    )
    args = parser.parse_args()

    from faster_whisper import WhisperModel

    print(f"Loading faster-whisper model '{args.model}' (int8, CPU)...")
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    if args.id_min is not None:
        print(f"Fetching segments with ID_SEGMENTO >= {args.id_min}...")
        segments = fetch_discarded_segments(id_segmento_min=args.id_min)[: args.limit]
    else:
        max_id = current_max_id_segmento()
        id_segmento_min = max(max_id - args.lookback, 0)
        print(f"Fetching segments with ID_SEGMENTO >= {id_segmento_min} (max={max_id})...")
        segments = fetch_discarded_segments(id_segmento_min=id_segmento_min)[-args.limit :]
    if not segments:
        print(
            f"No segments matched in the last {args.lookback} IDs -- try a larger --lookback, "
            "or confirm EMISORAS_MENCION opt-in / FECHA_MENCION for the pilot station."
        )
        return

    for row in segments:
        label = f"ID_SEGMENTO={row['ID_SEGMENTO']}"
        print(f"\n{'=' * 60}\n{label}  (DURACION={row['DURACION']}s, RUTA={row['RUTA']})")

        try:
            clip_path = crop_segment(row["RUTA"], row["INICIO"], row["DURACION"], row["CANAL"])
        except Exception as e:
            print(f"  crop failed: {e}")
            continue

        try:
            start = time.perf_counter()
            local_segments, info = model.transcribe(
                clip_path,
                language="es",
                vad_filter=True,
                condition_on_previous_text=False,
                no_speech_threshold=0.4,
                beam_size=5,
            )
            text_out = " ".join(seg.text.strip() for seg in local_segments)
            elapsed = time.perf_counter() - start

            clip_duration = info.duration
            rtf = elapsed / clip_duration if clip_duration else float("nan")

            print(f"  clip duration:   {clip_duration:.1f}s")
            print(f"  transcribe time: {elapsed:.1f}s")
            print(f"  real-time factor: {rtf:.2f}x  (<1.0 = faster than playback)")
            print(f"  transcript: {text_out}")
        finally:
            os.remove(clip_path)


if __name__ == "__main__":
    main()
