"""PyInstaller entry point for the Tool 2 executable."""

import sys

from src.tool2 import LAST_ID_TESTIGO_FILE, POLL_INTERVAL_SECONDS, main, run_forever

if __name__ == "__main__":
    if len(sys.argv) > 2:
        raise SystemExit(
            "usage: tool2.exe [id_testigo_min]\n"
            "With an argument: runs once, seeding/overriding the saved ID_TESTIGO "
            f"({LAST_ID_TESTIGO_FILE}) -- use this for a one-off backfill or to "
            "establish the very first starting point.\n"
            "With no argument: runs forever as a service, polling every "
            f"{POLL_INTERVAL_SECONDS}s (override via TOOL2_POLL_INTERVAL_SECONDS) "
            "and resuming from the saved ID_TESTIGO each cycle."
        )
    if len(sys.argv) == 2:
        main(id_testigo_min=int(sys.argv[1]))
    else:
        run_forever()
