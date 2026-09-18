import os

from src.tool2.constants import LAST_ID_TESTIGO_FILE
from src.tool2.queries import current_max_id_testigo


def read_last_id_testigo() -> int:
    """The ID_TESTIGO of the last testigo Tool 2 finished processing, so an
    hourly-scheduled run only looks at what's new since the previous run
    instead of rescanning SEGMENTO_SARA (100M+ rows) from scratch each time.
    If the state file doesn't exist yet (first-ever run), seeds it with the
    current MAX(ID_TESTIGO) and starts from there."""
    if not os.path.exists(LAST_ID_TESTIGO_FILE):
        seed = current_max_id_testigo()
        write_last_id_testigo(seed)
        return seed
    with open(LAST_ID_TESTIGO_FILE) as f:
        return int(f.read().strip())


def write_last_id_testigo(id_testigo: int) -> None:
    with open(LAST_ID_TESTIGO_FILE, "w") as f:
        f.write(str(id_testigo))
