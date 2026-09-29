import os
import threading
from collections import deque

from src.tool2.constants import LAST_ID_SEGMENTO_FILE
from src.tool2.queries import current_max_id_segmento


def read_last_id_segmento() -> int:
    """
    Reads the last checkpointed ID_SEGMENTO from the state file. If the file doesn't exist, it initializes it with the current maxmimum ID_SEGMENTO from the database and returns that value.
    """
    if not os.path.exists(LAST_ID_SEGMENTO_FILE):
        id_segmento = current_max_id_segmento()
        write_last_id_segmento(id_segmento)
        return id_segmento
    with open(LAST_ID_SEGMENTO_FILE) as f:
        return int(f.read().strip())


def write_last_id_segmento(id_segmento: int) -> None:
    with open(LAST_ID_SEGMENTO_FILE, "w") as f:
        f.write(str(id_segmento))


class BatchProgress:
    """
    Per-segment checkpoint tracking for one batch, so a mid-batch restart
    only re-touches segments still in flight. Segments must be ascending
    """

    def __init__(self, segments: list[dict], start_id_segmento_min: int):
        self._pending = deque(s["ID_SEGMENTO"] for s in segments)
        self._done_ahead = set()
        self._checkpoint = start_id_segmento_min - 1
        self._lock = threading.Lock()

    def mark_done(self, id_segmento: int) -> None:
        with self._lock:
            if self._pending and self._pending[0] == id_segmento:
                self._checkpoint = self._pending.popleft()
                while self._pending and self._pending[0] in self._done_ahead:
                    self._done_ahead.discard(self._pending[0])
                    self._checkpoint = self._pending.popleft()
            else:
                self._done_ahead.add(id_segmento)

    def safe_checkpoint(self) -> int:
        """
        Returns the last ID_SEGMENTO that has been fully processed and can be safely checkpointed.
        """
        with self._lock:
            return self._checkpoint + 1
