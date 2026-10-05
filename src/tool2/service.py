import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from src.db.db import db_test
from src.tool2.constants import (
    MAX_WORKERS,
    POLL_INTERVAL_SECONDS,
)
from src.tool2.logging_setup import format_exception_detail, logger
from src.tool2.pipeline import process_one_segment
from src.tool2.progress import (
    BatchProgress,
    read_last_id_segmento,
    write_last_id_segmento,
)
from src.tool2.queries import (
    fetch_discarded_segments,
)


def main(debug: bool = False) -> None:
    """
    Runs the service on segments where ID_SEGMENTO >= the last checkpointed ID_SEGMENTO.

    With debug=True, results (including a placeholder row for segments with no mentions) are written to the test database instead of production.

    It runs concurrently, spawning MAX_WROKERS threads to process segments in parallel. It keeps track of advances segment-by-segment, so if the service is restarted mid-batch it will only re-touch segments that were being processed, not everything since the batch's lowest ID_SEGMENTO.
    """
    global _progress_done
    id_segmento_min = read_last_id_segmento()

    segments = fetch_discarded_segments(id_segmento_min=id_segmento_min)
    total = len(segments)
    logger.info(
        f"id_segmento_min={id_segmento_min}: found {total} segment(s) to process"
    )
    _progress_done = 0

    batch_progress = BatchProgress(segments, id_segmento_min)

    if segments:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            list(
                executor.map(
                    lambda s: process_one_segment(
                        s, total, batch_progress, debug=debug
                    ),
                    segments,
                )
            )

    write_last_id_segmento(batch_progress.safe_checkpoint())
    logger.info(
        f"batch complete: checkpointed ID_SEGMENTO={batch_progress.safe_checkpoint()}"
    )


def run(debug: bool = False) -> None:
    """
    Service entrypoint: runs main() on a loop, keeping track of the ID_SEGMENTO. Fails or errors are logged and skipped, the next loop retries from the same saved position

    debug=True (the --debug flag of run_tool2.py) writes to the test database instead of production.
    """
    if debug:
        if db_test is None:
            raise RuntimeError(
                "--debug needs the test database -- set TEST_DB_SERVER_URL and TEST_DB_SERVER_DATABASE in .env"
            )
        logger.info("DEBUG mode: results are written to the test database, not production")

    while True:
        try:
            main(debug=debug)
        except Exception as e:  # noqa: BLE001
            logger.error(
                f"run failed, will retry next cycle: {format_exception_detail(e)}",
                exc_info=True,
            )

        next_time = datetime.now(tz=UTC).astimezone() + timedelta(
            seconds=POLL_INTERVAL_SECONDS
        )
        logger.info(
            f"sleeping {POLL_INTERVAL_SECONDS}s before next cycle..., starting again at {next_time} "
        )
        time.sleep(POLL_INTERVAL_SECONDS)
