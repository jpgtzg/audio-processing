import os
import sys
import tempfile
import time

from pydub import AudioSegment
from sqlalchemy import bindparam, text

from src.audio import transcribe_timestamped_segments
from src.db.db import engine
from src.extraction import extract_brand_mentions

TESTIGO_SHARE_TEMPLATE = os.environ.get("TESTIGO_SHARE_TEMPLATE", r"\\{hostname}\sara")
LAST_ID_TESTIGO_FILE = os.environ.get("TOOL2_LAST_ID_TESTIGO_FILE", "tool2_last_id_testigo.txt")
POLL_INTERVAL_SECONDS = int(os.environ.get("TOOL2_POLL_INTERVAL_SECONDS", 60 * 60))
ESTATUS_DESCARTADO_LOCUTOR: int = 10
ESTATUS_DESCARTADO_NOTICIERO: int = 11
ESTATUS_DESCARTADO_CANCION: int = 12
TOOL2_ESTATUS_IDS: list[int] = [
    ESTATUS_DESCARTADO_LOCUTOR,
    ESTATUS_DESCARTADO_NOTICIERO,
    ESTATUS_DESCARTADO_CANCION,
]


def fetch_discarded_segments(
    estatus_ids: list[int] = TOOL2_ESTATUS_IDS,
    id_testigo_min: int | None = None,
) -> list[dict]:
    """SEGMENTO_SARA rows discarded for one of the given ID_ESTATUS_SEGMENTO
    reasons, joined against TESTIGO_SARA for HOSTNAME/ARCHIVO so each row is
    enough to locate and crop the actual clip (see resolve_testigo_path()).

    SEGMENTO_SARA is 100M+ rows (12M+ for song-discard alone) -- always pass
    id_testigo_min (or add another bound) rather than pulling the whole table."""
    query = text(
        """
        SELECT s.ID_SEGMENTO, s.ID_TESTIGO, s.ID_ESTATUS_SEGMENTO, s.INICIO, s.DURACION,
               t.HOSTNAME, t.ARCHIVO, t.CANAL
        FROM SEGMENTO_SARA s
        JOIN TESTIGO_SARA t ON s.ID_TESTIGO = t.ID_TESTIGO
        WHERE s.ID_ESTATUS_SEGMENTO IN :estatus_ids
          AND (:id_testigo_min IS NULL OR s.ID_TESTIGO >= :id_testigo_min)
        """
    ).bindparams(bindparam("estatus_ids", expanding=True))

    with engine.connect() as conn:
        rows = (
            conn.execute(
                query,
                {"estatus_ids": list(estatus_ids), "id_testigo_min": id_testigo_min},
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def resolve_testigo_path(hostname: str, archivo: str) -> str:
    """Builds the UNC path to a TESTIGO_SARA recording from its capture host and
    filename, e.g. \\sara3\\sara\\mp3\\<ARCHIVO>. See TESTIGO_SHARE_TEMPLATE above."""
    share_dir = TESTIGO_SHARE_TEMPLATE.format(hostname=hostname.lower())
    return os.path.join(share_dir, archivo)


def crop_segment(testigo_path: str, inicio: float, duracion: float, canal: int) -> str:
    """Crops [inicio, inicio + duracion] out of a testigo recording and exports it
    to a temp wav file for transcription. Assumes INICIO/DURACION are both in
    seconds (SEGMENTO_SARA's own offset convention into its parent testigo --
    distinct from ALTAS_SARA_FP.INICIO, which is confirmed to be milliseconds).
    Not yet literally confirmed with the client; worth a quick sanity check by ear
    before this goes live, the same way ALTAS_SARA_FP's units were.

    Client confirmed (2026-09-04): each file under mp3/ actually carries two
    simultaneous, unrelated station emissions multiplexed onto stereo left/right --
    TESTIGO_SARA.CANAL says which one this row is (1=left, 2=right). Isolating the
    right channel here (rather than mixing both down to mono) is required, not
    optional -- feeding Whisper both channels blended together is a likely cause
    of the garbled/looping transcripts seen before this fix."""
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
    testigo_path = resolve_testigo_path(segment["HOSTNAME"], segment["ARCHIVO"])
    clip_path = crop_segment(
        testigo_path, segment["INICIO"], segment["DURACION"], segment["CANAL"]
    )

    try:
        segments = transcribe_timestamped_segments(clip_path)
    finally:
        os.remove(clip_path)

    transcript = " ".join(s["text"] for s in segments)
    mentions = extract_brand_mentions(segments)

    return [
        {
            "transcript": transcript,
            "id_segmento": segment["ID_SEGMENTO"],
            "id_testigo": segment["ID_TESTIGO"],
            "id_estatus_segmento": segment["ID_ESTATUS_SEGMENTO"],
            **mention,
        }
        for mention in mentions
    ]


def save_mentions(mentions: list[dict]) -> None:
    """Inserts detected brand mentions into MENCIONES_COMERCIALES (see
    scripts/create_mentions_table.py -- must be run once, by a DB login with
    CREATE TABLE rights, before this will work; the login used for day-to-day
    reads/writes only has SELECT so far).

    TITULO currently reuses MARCA -- Tool 2 doesn't generate a separate spot
    title the way Tool 1's extraction does; revisit if the client wants one."""
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
            (ID_SEGMENTO, ID_TESTIGO, ID_ESTATUS_SEGMENTO, TITULO, ANUNCIANTE, MARCA,
             INICIO_MENCION, FIN_MENCION, TRANSCRIPCION)
        VALUES
            (:id_segmento, :id_testigo, :id_estatus_segmento, :titulo, :anunciante, :marca,
             :inicio_mencion, :fin_mencion, :transcripcion)
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
                    "titulo": m.get("marca"),
                    "anunciante": m.get("anunciante"),
                    "marca": m.get("marca"),
                    "inicio_mencion": m["start"],
                    "fin_mencion": m["end"],
                    "transcripcion": m.get("transcript"),
                }
                for m in mentions
            ],
        )
        conn.commit()


def read_last_id_testigo() -> int | None:
    """The ID_TESTIGO of the last testigo Tool 2 finished processing, so an
    hourly-scheduled run only looks at what's new since the previous run
    instead of rescanning SEGMENTO_SARA (100M+ rows) from scratch each time.
    None the first time this ever runs -- caller must supply an explicit
    starting point in that case."""
    if not os.path.exists(LAST_ID_TESTIGO_FILE):
        return None
    with open(LAST_ID_TESTIGO_FILE) as f:
        content = f.read().strip()
    return int(content) if content else None


def write_last_id_testigo(id_testigo: int) -> None:
    with open(LAST_ID_TESTIGO_FILE, "w") as f:
        f.write(str(id_testigo))


def main(id_testigo_min: int | None = None) -> None:
    """Runs once over every discarded segment with ID_TESTIGO >= id_testigo_min.
    If id_testigo_min isn't given, resumes from the last ID_TESTIGO this
    process finished on (see read_last_id_testigo()) -- pass it explicitly
    only for a one-off backfill/dry run. On a normal run, advances the saved
    ID_TESTIGO past every testigo actually seen this time, regardless of
    per-segment errors, so a permanently-missing recording (FileNotFoundError)
    doesn't stall future runs retrying it forever."""
    resumed = id_testigo_min is None
    if resumed:
        id_testigo_min = read_last_id_testigo()
        if id_testigo_min is None:
            raise SystemExit(
                f"no saved progress in {LAST_ID_TESTIGO_FILE} -- run once with an "
                "explicit id_testigo_min to establish a starting point"
            )

    segments = fetch_discarded_segments(id_testigo_min=id_testigo_min)
    total = len(segments)
    max_id_testigo = id_testigo_min - 1

    for done, segment in enumerate(segments, start=1):
        label = f"ID_SEGMENTO={segment['ID_SEGMENTO']}"
        print("=" * 40)
        print("Processing segment:", label)
        max_id_testigo = max(max_id_testigo, segment["ID_TESTIGO"])

        try:
            results = process(segment)
        except FileNotFoundError:
            print(f"[{done}/{total}] {label}: recording not reachable, skipping")
            continue

        if not results:
            print(f"[{done}/{total}] {label}: no brand mentions found")
            continue

        save_mentions(results)
        for result in results:
            print(
                f"[{done}/{total}] {label}: {result['anunciante']} / {result['marca']} "
                f"({result['start']:.2f}s-{result['end']:.2f}s)"
            )

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
            print(f"run failed, will retry next cycle: {e}")
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
