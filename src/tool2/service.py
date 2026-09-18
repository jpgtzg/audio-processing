import threading
import time
from concurrent.futures import ThreadPoolExecutor

from src.tool2 import checkpoint
from src.tool2.constants import MAX_WORKERS, POLL_INTERVAL_SECONDS
from src.tool2.logging_setup import format_exception_detail, logger
from src.tool2.pipeline import process
from src.tool2.queries import fetch_discarded_segments, save_mentions, segment_already_recorded

_progress_lock = threading.Lock()
_progress_done = 0


def _process_one_segment(segment: dict, total: int) -> None:
    """Runs process() + save_mentions() for a single segment and logs the
    outcome, swallowing (never re-raising) any failure -- factored out of
    main() so it can be submitted to a thread pool. Any exception here is
    handled and logged exactly the same way whether called from a thread
    pool worker or a plain sequential loop (MAX_WORKERS=1)."""
    global _progress_done
    with _progress_lock:
        _progress_done += 1
        done = _progress_done

    label = f"ID_SEGMENTO={segment['ID_SEGMENTO']}"

    if segment_already_recorded(segment["ID_SEGMENTO"]):
        logger.info(f"[{done}/{total}] {label}: already has mention(s) recorded, skipping")
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
        # must not abort the whole run -- main() advances max_id_testigo past
        # every segment attempted this run regardless of outcome, so a
        # permanently-failing segment doesn't stall future runs retrying it
        # forever. Log the full traceback plus whatever extra detail the
        # exception carries (see format_exception_detail()) and move on.
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


def main(id_testigo_min: int | None = None) -> None:
    """Runs once over every discarded segment with ID_TESTIGO >= id_testigo_min,
    processing up to MAX_WORKERS segments concurrently (see
    _process_one_segment()). If id_testigo_min isn't given, resumes from the
    last ID_TESTIGO this process finished on (see checkpoint.read_last_id_testigo())
    -- pass it explicitly only for a one-off backfill/dry run. On a normal run,
    advances the saved ID_TESTIGO past every testigo seen this time regardless
    of per-segment errors, so a permanently-failing segment doesn't stall
    future runs retrying it forever."""
    global _progress_done
    resumed = id_testigo_min is None
    if resumed:
        id_testigo_min = checkpoint.read_last_id_testigo()

    segments = fetch_discarded_segments(id_testigo_min=id_testigo_min)
    total = len(segments)
    logger.info(f"id_testigo_min={id_testigo_min}: found {total} segment(s) to process")
    _progress_done = 0

    # Computed upfront over the whole batch since segments process out of
    # order under concurrency -- every fetched segment counts toward the
    # saved position regardless of outcome.
    max_id_testigo = max([id_testigo_min - 1] + [s["ID_TESTIGO"] for s in segments])

    if segments:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            list(executor.map(lambda s: _process_one_segment(s, total), segments))

    if resumed:
        checkpoint.write_last_id_testigo(max_id_testigo + 1)


def run_forever(poll_interval_seconds: int = POLL_INTERVAL_SECONDS) -> None:
    """Service entrypoint: runs main() on a loop, sleeping poll_interval_seconds
    between runs, resuming from the saved ID_TESTIGO each time. A single run's
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
