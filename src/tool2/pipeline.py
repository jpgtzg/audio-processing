import os
import threading

from src.audio import transcribe_timestamped_segments
from src.extraction import extract_brand_mentions
from src.tool2.crop import crop_segment
from src.tool2.logging_setup import format_exception_detail, logger
from src.tool2.progress import (
    BatchProgress,
    write_last_id_segmento,
)
from src.tool2.queries import save_mentions, segment_already_recorded

_progress_lock = threading.Lock()
_progress_done = 0


def _process(segment: dict) -> list[dict]:
    """
    Transcribes a single segment and returns one row per detected
    brand mention (a clip can contain zero, one, or several), each carrying
    the source id_segmento/id_testigo/id_estatus_segmento so it can be traced
    back
    """
    clip_path = crop_segment(
        segment["RUTA"], segment["INICIO"], segment["DURACION"], segment["CANAL"]
    )

    try:
        segments = transcribe_timestamped_segments(clip_path)
        full_transcript = " ".join(s["text"] for s in segments)
        mentions = extract_brand_mentions(segments)
    finally:
        os.remove(clip_path)

    return [
        {
            "id_segmento": segment["ID_SEGMENTO"],
            "id_testigo": segment["ID_TESTIGO"],
            "id_estatus_segmento": segment["ID_ESTATUS_SEGMENTO"],
            "full_transcript": full_transcript,
            **mention,
        }
        for mention in mentions
    ]


def process_one_segment(
    segment: dict, total: int, batch_progress: BatchProgress
) -> None:
    """
    Runs process() and save_mentions() for a single segment and logs the outcome.
    Marks the segment as done in batch_progress and persists the resulting checkpoint
    """

    global _progress_done
    try:
        with _progress_lock:
            _progress_done += 1
            done = _progress_done

        label = f"ID_SEGMENTO={segment['ID_SEGMENTO']}"

        if segment_already_recorded(segment["ID_SEGMENTO"]):
            logger.info(
                f"[{done}/{total}] {label}: already has mention(s) recorded, skipping"
            )
            return

        logger.info(f"[{done}/{total}] Processing segment: {label}")

        try:
            results = _process(segment)
        except FileNotFoundError:
            logger.info(f"[{done}/{total}] {label}: recording not reachable, skipping")
            return
        except Exception as e:  # noqa: BLE001
            logger.error(
                f"[{done}/{total}] {label}: processing failed ({format_exception_detail(e)}), skipping",
                exc_info=True,
            )
            return

        if not results:
            logger.info(f"[{done}/{total}] {label}: no brand mentions found")
            return

        save_mentions(results)
        for result in results:
            logger.info(
                f"[{done}/{total}] {label}: {result['anunciante']} / {result['marca']} "
                f"({result['start']:.2f}s-{result['end']:.2f}s)"
            )
    finally:
        batch_progress.mark_done(segment["ID_SEGMENTO"])
        write_last_id_segmento(batch_progress.safe_checkpoint())
