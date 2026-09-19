import threading
import time
from concurrent.futures import ThreadPoolExecutor

from src.tool2.constants import LAST_ID_SEGMENTO_FILE, MAX_WORKERS, POLL_INTERVAL_SECONDS
from src.tool2.logging_setup import format_exception_detail, logger
from src.tool2.pipeline import process
from src.tool2.progress import BatchProgress, read_last_id_segmento, write_last_id_segmento
from src.tool2.queries import (
    fetch_discarded_segments,
    save_mentions,
    segment_already_recorded,
)

_progress_lock = threading.Lock()
_progress_done = 0


def _process_one_segment(
    segment: dict, total: int, batch_progress: BatchProgress
) -> None:
    """Runs process() + save_mentions() for a single segment and logs the
    outcome, swallowing (never re-raising) any failure -- factored out of
    main() so it can be submitted to a thread pool. Any exception here is
    handled and logged exactly the same way whether called from a thread
    pool worker or a plain sequential loop (MAX_WORKERS=1).

    Always marks this segment done in batch_progress (and persists the
    resulting checkpoint) in a finally block, regardless of outcome --
    skipped, failed, or successful all count as "handled" for the purpose of
    advancing the safe checkpoint prefix (see progress.BatchProgress)."""
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
            results = process(segment)
        except FileNotFoundError:
            logger.info(f"[{done}/{total}] {label}: recording not reachable, skipping")
            return
        except Exception as e:
            # Any other per-segment failure (corrupt/locked file, decode error,
            # OS-level path errors, transient share hiccups, API errors, etc.)
            # must not abort the whole run -- log the full traceback plus
            # whatever extra detail the exception carries (see
            # format_exception_detail()) and move on.
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


def main() -> None:
    """Runs once over every discarded segment with ID_SEGMENTO >= the last
    checkpointed ID_SEGMENTO (see read_last_id_segmento()),
    processing up to MAX_WORKERS segments concurrently (see
    _process_one_segment()). The checkpoint advances segment-by-segment as
    work completes (see progress.BatchProgress), not just once at the end of
    the batch, so a mid-batch restart only re-touches segments genuinely
    still in flight."""
    global _progress_done
    id_segmento_min = read_last_id_segmento()

    segments = fetch_discarded_segments(id_segmento_min=id_segmento_min)
    total = len(segments)
    logger.info(f"id_segmento_min={id_segmento_min}: found {total} segment(s) to process")
    _progress_done = 0

    batch_progress = BatchProgress(segments, id_segmento_min)

    if segments:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            list(
                executor.map(
                    lambda s: _process_one_segment(s, total, batch_progress),
                    segments,
                )
            )

    write_last_id_segmento(batch_progress.safe_checkpoint())


def run_forever(poll_interval_seconds: int = POLL_INTERVAL_SECONDS) -> None:
    """Service entrypoint: runs main() on a loop, sleeping poll_interval_seconds
    between runs, resuming from the saved ID_SEGMENTO each time. A single run's
    failure (e.g. a transient DB or share outage) is logged and skipped rather
    than killing the service -- the next iteration just retries from the same
    saved position."""
    while True:
        try:
            main()
        except Exception as e:
            logger.error(
                f"run failed, will retry next cycle: {format_exception_detail(e)}",
                exc_info=True,
            )
        time.sleep(poll_interval_seconds)


def run(argv: list[str]) -> None:
    """Shared CLI entrypoint for both `python -m src.tool2` and the packaged
    tool2.exe (see run_tool2.py). Runs forever as a service, polling on an
    interval and always resuming from the saved ID_SEGMENTO
    (read_last_id_segmento()) each cycle. Takes no arguments --
    to change the starting point, edit LAST_ID_SEGMENTO_FILE directly."""
    if argv:
        raise SystemExit(
            "usage: tool2\n"
            f"Runs forever as a service, polling every {POLL_INTERVAL_SECONDS}s "
            "(override via TOOL2_POLL_INTERVAL_SECONDS) and always resuming from "
            f"the saved ID_SEGMENTO ({LAST_ID_SEGMENTO_FILE}) each cycle. To change "
            "the starting point, edit that file directly."
        )
    run_forever()
