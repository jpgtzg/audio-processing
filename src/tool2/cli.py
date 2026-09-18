from src.tool2.constants import LAST_ID_TESTIGO_FILE, POLL_INTERVAL_SECONDS
from src.tool2.service import main, run_forever


def run(argv: list[str]) -> None:
    """Shared CLI entrypoint for both `python -m src.tool2` and the packaged
    tool2.exe (see run_tool2.py). With one argument: runs once, seeding/
    overriding the saved ID_TESTIGO -- use for a one-off backfill or to
    establish the first starting point. With no argument: runs forever as a
    service, polling on an interval and resuming from the saved ID_TESTIGO
    each cycle."""
    if len(argv) > 1:
        raise SystemExit(
            "usage: tool2 [id_testigo_min]\n"
            "With an argument: runs once, seeding/overriding the saved ID_TESTIGO "
            f"({LAST_ID_TESTIGO_FILE}) -- use this for a one-off backfill or to "
            "establish the very first starting point.\n"
            "With no argument: runs forever as a service, polling every "
            f"{POLL_INTERVAL_SECONDS}s (override via TOOL2_POLL_INTERVAL_SECONDS) "
            "and resuming from the saved ID_TESTIGO each cycle."
        )
    if len(argv) == 1:
        main(id_testigo_min=int(argv[0]))
    else:
        run_forever()
