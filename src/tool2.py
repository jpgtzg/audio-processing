import os
import re

from sqlalchemy import bindparam, text

from src.audio import transcribe_timestamped_segments
from src.db.db import engine
from src.extraction import extract_brand_mentions

# Mirrors tool1.py's INPUT_DIR pattern. Unlike Tool 1, the client hasn't shared a
# local wav dump of discarded/oversized segments yet (client_data only has wav2,
# which is Tool 1's ALTAS_SARA_FP-backed set) -- point this at whatever sample set
# is available for now. See scripts/slice_sample.py for one way to populate this
# folder from client_data/Audios Completos XET-FM.
INPUT_DIR = "tool2_input"

FIELDS = ["filename", "marca", "anunciante", "start", "end", "transcript"]

# SEGMENTO_SARA.ID_ESTATUS_SEGMENTO links to CAT_ESTATUS_SEGMENTO (confirmed live
# against the client's test DB). Client confirmed (2026-08-17) Tool 2 should cover
# these three discard reasons:
ESTATUS_DESCARTADO_LOCUTOR: int = 10  # "Descartado por Locutor"
ESTATUS_DESCARTADO_NOTICIERO: int = 11  # "Descartado por Noticiero"
ESTATUS_DESCARTADO_CANCION: int = 12  # "Descartado por Cancion"

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
    reasons. Note this only gives segment-level offsets (INICIO/DURACION) into
    the parent TESTIGO_SARA recording -- resolving an actual wav clip still needs
    a join against TESTIGO_SARA (HOSTNAME/ARCHIVO) plus a crop step, same as
    Tool 1's file-access story, which isn't wired up here yet.

    SEGMENTO_SARA is 100M+ rows (12M+ for song-discard alone) -- always pass
    id_testigo_min (or add another bound) rather than pulling the whole table."""
    query = text(
        """
        SELECT ID_SEGMENTO, ID_TESTIGO, ID_ESTATUS_SEGMENTO, INICIO, DURACION
        FROM SEGMENTO_SARA
        WHERE ID_ESTATUS_SEGMENTO IN :estatus_ids
          AND (:id_testigo_min IS NULL OR ID_TESTIGO >= :id_testigo_min)
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


def natural_sort_key(filename: str) -> list:
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r"(\d+)", filename)
    ]


def process(filename: str, segment: dict | None = None) -> list[dict]:
    """Transcribes a single discarded/oversized segment and returns one row per
    detected brand mention (a clip can contain zero, one, or several).

    `segment` is the source SEGMENTO_SARA row (one item from
    fetch_discarded_segments()) so each mention can be traced back to where it
    came from and saved via save_mentions(). Left optional for local ad-hoc
    testing against a wav that has no known DB row -- those mentions come back
    without id_segmento/id_testigo/id_estatus_segmento and save_mentions() will
    reject them."""
    path = os.path.join(INPUT_DIR, filename)
    segments = transcribe_timestamped_segments(path)
    transcript = " ".join(s["text"] for s in segments)

    mentions = extract_brand_mentions(segments)

    return [
        {
            "filename": filename,
            "transcript": transcript,
            "id_segmento": segment["ID_SEGMENTO"] if segment else None,
            "id_testigo": segment["ID_TESTIGO"] if segment else None,
            "id_estatus_segmento": segment["ID_ESTATUS_SEGMENTO"] if segment else None,
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


def main():
    # Local-file testing loop only: there's no mapping yet from a local wav
    # filename to a real SEGMENTO_SARA row (see docs/handoff.md), so this can't
    # call save_mentions(). Once file access resolves that link, drive
    # save_mentions() from fetch_discarded_segments() + process(file, segment)
    # instead of this loop.
    files = sorted(
        (f for f in os.listdir(INPUT_DIR) if f.endswith((".wav", ".mp3", ".mp4"))),
        key=natural_sort_key,
    )

    total = len(files)

    for done, file in enumerate(files, start=1):
        print("=" * 40)
        print("Processing file:", file)
        results = process(file)
        if not results:
            print(f"[{done}/{total}] {file}: no brand mentions found")
            continue
        for result in results:
            print(
                f"[{done}/{total}] {file}: {result['anunciante']} / {result['marca']} "
                f"({result['start']:.2f}s-{result['end']:.2f}s)"
            )


if __name__ == "__main__":
    main()
