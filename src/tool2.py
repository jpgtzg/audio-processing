import logging
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from pydub import AudioSegment
from sqlalchemy import bindparam, text

from src.audio import transcribe_timestamped_segments
from src.db.db import engine
from src.extraction import extract_brand_mentions

LOG_FILE = os.environ.get("TOOL2_LOG_FILE", "tool2.log")

logger = logging.getLogger("tool2")
logger.setLevel(logging.INFO)
if not logger.handlers:
    # Guards against duplicate handlers (and duplicate log lines) if this
    # module gets imported more than once in the same process, e.g. from
    # scripts/tool2_test.py.
    _formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(_formatter)
    logger.addHandler(_console_handler)
    try:
        _file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        _file_handler.setFormatter(_formatter)
        logger.addHandler(_file_handler)
    except OSError:
        # Don't let an unwritable log directory take down the whole service --
        # console logging alone still works.
        logger.warning(f"could not open log file {LOG_FILE!r}, file logging disabled")


def _format_exception_detail(e: Exception) -> str:
    """Pulls out whatever extra diagnostic detail an exception carries beyond
    repr(e) -- status code, response body/request ID, error body. Duck-types
    rather than importing openai's exception classes, since a DB (pymssql) or
    OS-level exception can turn up here too and won't have these attributes."""
    parts = [repr(e)]

    status_code = getattr(e, "status_code", None)
    if status_code is not None:
        parts.append(f"status_code={status_code}")

    response = getattr(e, "response", None)
    if response is not None:
        request_id = None
        headers = getattr(response, "headers", None)
        if headers is not None:
            request_id = headers.get("x-request-id")
        if request_id:
            parts.append(f"request_id={request_id}")
        response_text = getattr(response, "text", None)
        if response_text:
            parts.append(f"response_body={response_text}")

    body = getattr(e, "body", None)
    if body is not None:
        parts.append(f"body={body}")

    return " | ".join(parts)


LAST_ID_TESTIGO_FILE = os.environ.get("TOOL2_LAST_ID_TESTIGO_FILE", "tool2_last_id_testigo.txt")
POLL_INTERVAL_SECONDS = int(os.environ.get("TOOL2_POLL_INTERVAL_SECONDS", 60 * 60))
# Segments are processed concurrently (see main()) -- the pipeline is I/O-bound
# (API calls, network file reads, DB writes), so this overlaps wait time
# without needing more CPU. Kept modest by default to stay under OpenAI
# per-account rate limits and SQLAlchemy's default connection pool size.
MAX_WORKERS = int(os.environ.get("TOOL2_MAX_WORKERS", 5))
ESTATUS_DESCARTADO_LOCUTOR: int = 10
ESTATUS_DESCARTADO_NOTICIERO: int = 11
ESTATUS_DESCARTADO_CANCION: int = 12
ESTATUS_DESCARTADO_INCONSISTENCIA: int = 13
ESTATUS_DESCARTADO_DURACION_MINIMA: int = 14
ESTATUS_DESCARTADO_GENERICO: int = 15
ESTATUS_DESCARTADO_AUDITORIA: int = 16
ESTATUS_DESCARTADO_NAC: int = 17
ESTATUS_DESCARTADO_ALTAS_AUTOMATICAS: int = 18
ESTATUS_DESCARTADO_REGLA: int = 21
TOOL2_ESTATUS_IDS: list[int] = [
    ESTATUS_DESCARTADO_LOCUTOR,
    ESTATUS_DESCARTADO_NOTICIERO,
    ESTATUS_DESCARTADO_CANCION,
    ESTATUS_DESCARTADO_INCONSISTENCIA,
    ESTATUS_DESCARTADO_DURACION_MINIMA,
    ESTATUS_DESCARTADO_GENERICO,
    ESTATUS_DESCARTADO_AUDITORIA,
    ESTATUS_DESCARTADO_NAC,
    ESTATUS_DESCARTADO_ALTAS_AUTOMATICAS,
    ESTATUS_DESCARTADO_REGLA,
]


@lru_cache(maxsize=1)
def get_motivo_descarte_labels() -> dict[int, str]:
    """Live-pulled MOTIVO_DESCARTE label for every code in TOOL2_ESTATUS_IDS,
    sourced from CAT_ESTATUS_SEGMENTO.DESCRIPCION rather than a hand-maintained
    dict, so new codes don't need a matching label added by hand. Cached
    per-process since the catalog changes rarely, same pattern as
    get_categorias() in src/extraction.py."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ID_ESTATUS_SEGMENTO, DESCRIPCION FROM CAT_ESTATUS_SEGMENTO "
                "WHERE ID_ESTATUS_SEGMENTO IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": TOOL2_ESTATUS_IDS},
        ).all()
    return {row.ID_ESTATUS_SEGMENTO: row.DESCRIPCION for row in rows}


TESTIGO_ESTATUS_TERMINADO: int = 10
TESTIGO_ESTATUS_BORRADO: int = 20
TOOL2_TESTIGO_ESTATUS_IDS: list[int] = [
    TESTIGO_ESTATUS_TERMINADO,
    TESTIGO_ESTATUS_BORRADO,
]


def fetch_discarded_segments(
    estatus_ids: list[int] = TOOL2_ESTATUS_IDS,
    testigo_estatus_ids: list[int] = TOOL2_TESTIGO_ESTATUS_IDS,
    id_testigo_min: int | None = None,
) -> list[dict]:
    """SEGMENTO_SARA rows discarded for one of the given ID_ESTATUS_SEGMENTO
    reasons, joined to resolve a playable clip's path (RUTA) and channel
    (CANAL) directly, scoped to stations opted into EMISORAS_MENCION.

    - Only rows for a station with EMISORAS_MENCION.MENCIONES=1, on/after that
      station's own FECHA_MENCION control date, are returned.
    - Only testigos SARA itself has finished archiving to backup storage
      (ID_ESTATUS_TESTIGO IN (10, 20)) are eligible -- MULTIMEDIA_ARCHIVO/
      MULTIMEDIA/HOST resolve the actual backup path (RUTA), which is built
      with plain SQL string concatenation rather than reassembled from parts
      in Python, so the path is never touched on the Python side.
    - MULTIMEDIA has two rows per MULTIMEDIA_ARCHIVO (one per CANAL) with an
      identical RUTA/ARCHIVO/HOST, since the archived file is still the same
      stereo dual-emission recording -- `mm.CANAL = 1` just picks one to avoid
      doubling every segment. The returned TESTIGO_SARA.CANAL is what
      actually tells crop_segment() which channel to isolate from the audio.

    SEGMENTO_SARA is 100M+ rows (12M+ for song-discard alone) -- always pass
    id_testigo_min (or add another bound) rather than pulling the whole table."""
    query = text(
        r"""
        SELECT s.ID_SEGMENTO, s.ID_TESTIGO, s.ID_ESTATUS_SEGMENTO, s.INICIO, s.DURACION,
               t.CANAL,
               '\\' + ho.NOM_HOST + '\' + mm.RUTA + '\' + mm.ARCHIVO AS RUTA
        FROM SEGMENTO_SARA s
        JOIN TESTIGO_SARA t ON s.ID_TESTIGO = t.ID_TESTIGO
        JOIN EMISORAS_MENCION ee ON ee.ID_EMISORA = t.ID_EMISORA
        JOIN MULTIMEDIA_ARCHIVO mua ON t.ID_MULTIMEDIA_ARCHIVO = mua.ID_MULTIMEDIA_ARCHIVO
        JOIN MULTIMEDIA mm ON mm.ID_MULTIMEDIA_ARCHIVO = mua.ID_MULTIMEDIA_ARCHIVO AND mm.CANAL = 1
        JOIN HOST ho ON mm.ID_HOST = ho.ID_HOST
        WHERE s.ID_ESTATUS_SEGMENTO IN :estatus_ids
          AND t.ID_ESTATUS_TESTIGO IN :testigo_estatus_ids
          AND ee.MENCIONES = 1
          AND ee.FECHA_MENCION IS NOT NULL
          AND ee.FECHA_MENCION <= t.FECHA_INICIO
          AND (:id_testigo_min IS NULL OR s.ID_TESTIGO >= :id_testigo_min)
        """
    ).bindparams(
        bindparam("estatus_ids", expanding=True),
        bindparam("testigo_estatus_ids", expanding=True),
    )

    with engine.connect() as conn:
        rows = (
            conn.execute(
                query,
                {
                    "estatus_ids": list(estatus_ids),
                    "testigo_estatus_ids": list(testigo_estatus_ids),
                    "id_testigo_min": id_testigo_min,
                },
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def crop_segment(testigo_path: str, inicio: float, duracion: float, canal: int) -> str:
    """Crops [inicio, inicio + duracion] out of a testigo recording and exports
    it to a temp wav file for transcription. INICIO/DURACION are in seconds
    (distinct from ALTAS_SARA_FP.INICIO, which is milliseconds).

    Each backup file multiplexes two unrelated station emissions onto stereo
    left/right; CANAL (1=left, 2=right) says which one this row is. Isolating
    that single channel (rather than downmixing both to mono) is required --
    feeding Whisper both channels blended together produces garbled, looping
    transcripts."""
    audio = AudioSegment.from_file(testigo_path)
    if audio.channels >= 2:
        if canal not in (1, 2):
            raise ValueError(f"CANAL must be 1 or 2 to pick a channel, got {canal!r}")
        audio = audio.split_to_mono()[canal - 1]

    start_ms = int(inicio * 1000)
    end_ms = start_ms + int(duracion * 1000)

    tmp_path = tempfile.mktemp(suffix=".wav")
    audio[start_ms:end_ms].export(tmp_path, format="wav")
    return tmp_path


def process(segment: dict) -> list[dict]:
    """Transcribes a single discarded/oversized segment (one row from
    fetch_discarded_segments()) and returns one row per detected brand mention
    (a clip can contain zero, one, or several), each carrying the source
    id_segmento/id_testigo/id_estatus_segmento so it can be traced back and
    saved via save_mentions()."""
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
            "motivo_descarte": get_motivo_descarte_labels().get(segment["ID_ESTATUS_SEGMENTO"]),
            "full_transcript": full_transcript,
            **mention,
        }
        for mention in mentions
    ]


def save_mentions(mentions: list[dict]) -> None:
    """Inserts detected brand mentions into MENCIONES_COMERCIALES (see
    scripts/create_mentions_table.py to create/migrate the table).

    ANUNCIANTE/MARCA carry the raw text Whisper extraction detected, kept even
    when it doesn't match anything in the catalogs so a capturista can still
    see/link the mention manually; NUM_ANUNC/NUM_MARCA carry the fuzzy-matched
    ANUNCIANTES.NUM_ANUNC/MARCAS.NUM_MARCA IDs when confident (see
    extraction.match_anunciante()/match_marca()), NULL otherwise. TRANSCRIPCION
    is only the sentence(s) spanning the mention itself; TRANSCRIPCION_COMPLETA
    keeps the entire clip's transcript for full context. TITULO currently
    reuses MARCA -- Tool 2 doesn't generate a separate spot title."""
    if not mentions:
        return

    missing_link = [m for m in mentions if m.get("id_segmento") is None]
    if missing_link:
        raise ValueError(
            f"{len(missing_link)} mention(s) have no id_segmento -- call process() "
            "with the source `segment` row before saving"
        )

    query = text(
        """
        INSERT INTO MENCIONES_COMERCIALES
            (ID_SEGMENTO, ID_TESTIGO, ID_ESTATUS_SEGMENTO, MOTIVO_DESCARTE, TITULO, ANUNCIANTE, MARCA,
             NUM_ANUNC, NUM_MARCA, INICIO_MENCION, FIN_MENCION, TRANSCRIPCION, TRANSCRIPCION_COMPLETA)
        VALUES
            (:id_segmento, :id_testigo, :id_estatus_segmento, :motivo_descarte, :titulo, :anunciante, :marca,
             :num_anunc, :num_marca, :inicio_mencion, :fin_mencion, :transcripcion, :transcripcion_completa)
        """
    )
    with engine.connect() as conn:
        conn.execute(
            query,
            [
                {
                    "id_segmento": m["id_segmento"],
                    "id_testigo": m["id_testigo"],
                    "id_estatus_segmento": m["id_estatus_segmento"],
                    "motivo_descarte": m.get("motivo_descarte")
                    or get_motivo_descarte_labels().get(m["id_estatus_segmento"]),
                    "titulo": m.get("marca"),
                    "anunciante": m.get("anunciante"),
                    "marca": m.get("marca"),
                    "num_anunc": m.get("num_anunc"),
                    "num_marca": m.get("num_marca"),
                    "inicio_mencion": m["start"],
                    "fin_mencion": m["end"],
                    "transcripcion": m.get("mention_transcript"),
                    "transcripcion_completa": m.get("full_transcript"),
                }
                for m in mentions
            ],
        )
        conn.commit()


def _current_max_id_testigo() -> int:
    """Live MAX(ID_TESTIGO) in TESTIGO_SARA -- used to seed the saved position
    the very first time the service runs, so it starts watching from "now"
    instead of backfilling the entire history."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT MAX(ID_TESTIGO) FROM TESTIGO_SARA")).scalar()


def read_last_id_testigo() -> int:
    """The ID_TESTIGO of the last testigo Tool 2 finished processing, so an
    hourly-scheduled run only looks at what's new since the previous run
    instead of rescanning SEGMENTO_SARA (100M+ rows) from scratch each time.
    If the state file doesn't exist yet (first-ever run), seeds it with the
    current MAX(ID_TESTIGO) and starts from there."""
    if not os.path.exists(LAST_ID_TESTIGO_FILE):
        seed = _current_max_id_testigo()
        write_last_id_testigo(seed)
        return seed
    with open(LAST_ID_TESTIGO_FILE) as f:
        return int(f.read().strip())


def write_last_id_testigo(id_testigo: int) -> None:
    with open(LAST_ID_TESTIGO_FILE, "w") as f:
        f.write(str(id_testigo))


_progress_lock = threading.Lock()
_progress_done = 0


def _segment_already_recorded(id_segmento: int) -> bool:
    """Whether ID_SEGMENTO already has at least one row in
    MENCIONES_COMERCIALES. LAST_ID_TESTIGO_FILE only advances once per entire
    batch (see main()), so a process killed mid-batch resumes from the same
    starting point next time and re-fetches segments already processed;
    save_mentions() is a plain INSERT with no dedup key. Called before the
    expensive transcription/extraction work, not just before the insert, so a
    repeat segment is cheap to skip, not just safe to skip.

    Doesn't catch a segment that was processed but found zero mentions (no
    row to check against) -- that gets reprocessed, which is wasted work but
    not harmful, since nothing gets inserted either way unless it genuinely
    finds something new."""
    with engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT TOP 1 1 FROM MENCIONES_COMERCIALES WHERE ID_SEGMENTO = :id_segmento"),
                {"id_segmento": id_segmento},
            ).scalar()
            is not None
        )


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

    if _segment_already_recorded(segment["ID_SEGMENTO"]):
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
        # exception carries (see _format_exception_detail()) and move on.
        logger.error(
            f"[{done}/{total}] {label}: processing failed ({_format_exception_detail(e)}), skipping",
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
    last ID_TESTIGO this process finished on (see read_last_id_testigo()) --
    pass it explicitly only for a one-off backfill/dry run. On a normal run,
    advances the saved ID_TESTIGO past every testigo seen this time regardless
    of per-segment errors, so a permanently-failing segment doesn't stall
    future runs retrying it forever."""
    global _progress_done
    resumed = id_testigo_min is None
    if resumed:
        id_testigo_min = read_last_id_testigo()

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
        write_last_id_testigo(max_id_testigo + 1)


def run_forever(poll_interval_seconds: int = POLL_INTERVAL_SECONDS) -> None:
    """Service entrypoint: runs main() on a loop, sleeping poll_interval_seconds
    between runs, resuming from the saved ID_TESTIGO each time (see main()/
    read_last_id_testigo()). A single run's failure (e.g. a transient DB or
    share outage) is logged and skipped rather than killing the service --
    the next iteration just retries from the same saved position."""
    while True:
        try:
            main()
        except Exception as e:
            logger.error(
                f"run failed, will retry next cycle: {_format_exception_detail(e)}",
                exc_info=True,
            )
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    if len(sys.argv) > 2:
        raise SystemExit(
            "usage: python -m src.tool2 [id_testigo_min]\n"
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
