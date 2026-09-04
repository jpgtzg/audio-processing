import os
import sys
import tempfile

from pydub import AudioSegment
from sqlalchemy import bindparam, text

from src.audio import transcribe_timestamped_segments
from src.db.db import engine
from src.extraction import extract_brand_mentions

# TESTIGO_SARA.ARCHIVO already embeds its own subfolder (e.g. "MP3\XHRED-...MP3"),
# so this points at the share root -- \\sara3\sara -- not the mp3 subfolder itself.
# Confirmed 2026-09-03: every ARCHIVO sampled from SARA3 starts with "MP3\", and the
# live \\sara3\sara\mp3 share lists those exact files flat, one level in.
TESTIGO_SHARE_TEMPLATE = os.environ.get(
    "TESTIGO_SHARE_TEMPLATE", r"\\{hostname}\sara"
)
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
               t.HOSTNAME, t.ARCHIVO
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


def crop_segment(testigo_path: str, inicio: float, duracion: float) -> str:
    """Crops [inicio, inicio + duracion] out of a testigo recording and exports it
    to a temp wav file for transcription. Assumes INICIO/DURACION are both in
    seconds (SEGMENTO_SARA's own offset convention into its parent testigo --
    distinct from ALTAS_SARA_FP.INICIO, which is confirmed to be milliseconds).
    Not yet literally confirmed with the client; worth a quick sanity check by ear
    before this goes live, the same way ALTAS_SARA_FP's units were."""
    audio = AudioSegment.from_file(testigo_path)
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
    clip_path = crop_segment(testigo_path, segment["INICIO"], segment["DURACION"])

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


def main(id_testigo_min: int) -> None:
    segments = fetch_discarded_segments(id_testigo_min=id_testigo_min)
    total = len(segments)

    for done, segment in enumerate(segments, start=1):
        label = f"ID_SEGMENTO={segment['ID_SEGMENTO']}"
        print("=" * 40)
        print("Processing segment:", label)

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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: python -m src.tool2 <id_testigo_min>\n"
            "SEGMENTO_SARA is 100M+ rows -- a lower bound on ID_TESTIGO is required."
        )
    main(id_testigo_min=int(sys.argv[1]))
