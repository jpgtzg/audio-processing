from functools import lru_cache

from sqlalchemy import bindparam, text

from src.db.db import engine
from src.tool2.constants import TOOL2_ESTATUS_IDS, TOOL2_TESTIGO_ESTATUS_IDS


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


def segment_already_recorded(id_segmento: int) -> bool:
    """Whether ID_SEGMENTO already has at least one row in
    MENCIONES_COMERCIALES. checkpoint.LAST_ID_TESTIGO_FILE only advances once
    per entire batch (see service.main()), so a process killed mid-batch
    resumes from the same starting point next time and re-fetches segments
    already processed; save_mentions() is a plain INSERT with no dedup key.
    Called before the expensive transcription/extraction work, not just
    before the insert, so a repeat segment is cheap to skip, not just safe
    to skip.

    Doesn't catch a segment that was processed but found zero mentions (no
    row to check against) -- that gets reprocessed, which is wasted work but
    not harmful, since nothing gets inserted either way unless it genuinely
    finds something new."""
    with engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT TOP 1 1 FROM MENCIONES_COMERCIALES WHERE ID_SEGMENTO = :id_segmento"
                ),
                {"id_segmento": id_segmento},
            ).scalar()
            is not None
        )


def save_mentions(mentions: list[dict]) -> None:
    """Inserts detected brand mentions into MENCIONES_COMERCIALES.

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


def current_max_id_testigo() -> int:
    """Live MAX(ID_TESTIGO) in TESTIGO_SARA -- used to seed the saved position
    the very first time the service runs, so it starts watching from "now"
    instead of backfilling the entire history."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT MAX(ID_TESTIGO) FROM TESTIGO_SARA")).scalar()
