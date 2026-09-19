"""Tool 2: finds embedded brand-mention "spots" inside content SARA's own
pipeline already discarded as non-commercial. See docs/handoff.md for the
current architecture and docs/progress.md for delivery history.

Split into submodules by concern:
    constants      -- discard/testigo status codes, env-configured settings
    logging_setup  -- the module logger + exception-detail formatting
    queries        -- all DB reads/writes (SEGMENTO_SARA, MENCIONES_COMERCIALES)
    crop           -- audio cropping/channel isolation
    pipeline       -- the per-segment transcribe + extract pipeline
    progress       -- last-processed-segment checkpoint state file, plus
                       per-segment completion tracking for one fetched batch
    service        -- orchestration: concurrent processing, the polling loop,
                       and the shared CLI entrypoint for run_tool2.py / `python -m src.tool2`

Re-exports the full previous flat-module API below so existing imports
(`from src.tool2 import X`) keep working unchanged."""

from src.tool2.constants import (
    ESTATUS_DESCARTADO_ALTAS_AUTOMATICAS,
    ESTATUS_DESCARTADO_AUDITORIA,
    ESTATUS_DESCARTADO_CANCION,
    ESTATUS_DESCARTADO_DURACION_MINIMA,
    ESTATUS_DESCARTADO_GENERICO,
    ESTATUS_DESCARTADO_INCONSISTENCIA,
    ESTATUS_DESCARTADO_LOCUTOR,
    ESTATUS_DESCARTADO_NAC,
    ESTATUS_DESCARTADO_NOTICIERO,
    ESTATUS_DESCARTADO_REGLA,
    LAST_ID_SEGMENTO_FILE,
    MAX_WORKERS,
    POLL_INTERVAL_SECONDS,
    TESTIGO_ESTATUS_BORRADO,
    TESTIGO_ESTATUS_TERMINADO,
    TOOL2_ESTATUS_IDS,
    TOOL2_TESTIGO_ESTATUS_IDS,
)
from src.tool2.crop import crop_segment
from src.tool2.logging_setup import LOG_FILE, format_exception_detail, logger
from src.tool2.pipeline import process
from src.tool2.progress import (
    BatchProgress,
    read_last_id_segmento,
    write_last_id_segmento,
)
from src.tool2.queries import (
    current_max_id_segmento,
    fetch_discarded_segments,
    get_motivo_descarte_labels,
    save_mentions,
    segment_already_recorded,
)
from src.tool2.service import _process_one_segment, main, run, run_forever

# Old underscore-prefixed names, kept as aliases for backward compatibility.
_current_max_id_segmento = current_max_id_segmento
_segment_already_recorded = segment_already_recorded
_format_exception_detail = format_exception_detail

__all__ = [
    "LOG_FILE",
    "logger",
    "format_exception_detail",
    "_format_exception_detail",
    "LAST_ID_SEGMENTO_FILE",
    "POLL_INTERVAL_SECONDS",
    "MAX_WORKERS",
    "ESTATUS_DESCARTADO_LOCUTOR",
    "ESTATUS_DESCARTADO_NOTICIERO",
    "ESTATUS_DESCARTADO_CANCION",
    "ESTATUS_DESCARTADO_INCONSISTENCIA",
    "ESTATUS_DESCARTADO_DURACION_MINIMA",
    "ESTATUS_DESCARTADO_GENERICO",
    "ESTATUS_DESCARTADO_AUDITORIA",
    "ESTATUS_DESCARTADO_NAC",
    "ESTATUS_DESCARTADO_ALTAS_AUTOMATICAS",
    "ESTATUS_DESCARTADO_REGLA",
    "TOOL2_ESTATUS_IDS",
    "TESTIGO_ESTATUS_TERMINADO",
    "TESTIGO_ESTATUS_BORRADO",
    "TOOL2_TESTIGO_ESTATUS_IDS",
    "get_motivo_descarte_labels",
    "fetch_discarded_segments",
    "crop_segment",
    "process",
    "save_mentions",
    "BatchProgress",
    "current_max_id_segmento",
    "_current_max_id_segmento",
    "read_last_id_segmento",
    "write_last_id_segmento",
    "segment_already_recorded",
    "_segment_already_recorded",
    "_process_one_segment",
    "main",
    "run",
    "run_forever",
]
