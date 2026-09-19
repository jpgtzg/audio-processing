import os
import threading
from collections import deque

from src.tool2.constants import LAST_ID_SEGMENTO_FILE
from src.tool2.queries import current_max_id_segmento


def read_last_id_segmento() -> int:
    """The ID_SEGMENTO to resume from, so a run only looks at what's new
    since the last one instead of rescanning SEGMENTO_SARA (100M+ rows) from
    scratch every time. If the state file doesn't exist yet (first-ever run),
    seeds it with the current MAX(ID_SEGMENTO) and starts from there."""
    if not os.path.exists(LAST_ID_SEGMENTO_FILE):
        seed = current_max_id_segmento()
        write_last_id_segmento(seed)
        return seed
    with open(LAST_ID_SEGMENTO_FILE) as f:
        return int(f.read().strip())


def write_last_id_segmento(id_segmento: int) -> None:
    with open(LAST_ID_SEGMENTO_FILE, "w") as f:
        f.write(str(id_segmento))


class BatchProgress:
    """Tracks per-segment completion for one fetched batch (see
    service.main()), so the checkpoint (read_last_id_segmento()/
    write_last_id_segmento() above) can advance at the segment level instead
    of only once per whole batch -- a mid-batch restart then only re-touches
    segments genuinely still in flight, not everything since the batch's
    lowest ID_SEGMENTO.

    Relies on `segments` being ordered ascending by ID_SEGMENTO (see the
    ORDER BY in queries.fetch_discarded_segments()) and on
    ThreadPoolExecutor.map() starting tasks strictly in that order: at any
    moment, if segment i has started, every segment before it has also
    started (though not necessarily finished). That means the only value
    that's always safe to check-point past is the ID_SEGMENTO of the longest
    *unbroken* completed run from the front -- not the highest ID_SEGMENTO
    completed so far, which could leave an earlier, still in-flight segment
    permanently skipped on the next run.

    Implemented as a queue of still-pending IDs plus a small set of IDs that
    finished out of order but are stuck behind a slower segment at the front
    -- not a full list of every segment in the batch. Since only MAX_WORKERS
    segments can ever be in flight at once, that "stuck ahead" set never
    grows past roughly MAX_WORKERS entries, so memory stays bounded by
    concurrency, not batch size, even for a very large batch on this
    forever-running service. mark_done() is also O(1) amortized per call
    instead of rescanning the whole batch every time.

    Purely in-memory, scoped to one batch/main() call -- only the integer
    returned by safe_checkpoint() gets persisted (via write_last_id_segmento()
    in service.py), not this queue itself."""

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
        """The next ID_SEGMENTO to resume from: one past the longest
        unbroken run of completed segments from the front."""
        with self._lock:
            return self._checkpoint + 1
