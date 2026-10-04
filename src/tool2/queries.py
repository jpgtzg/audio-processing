from sqlalchemy import text

from src.db.db import db_test, engine


def fetch_discarded_segments(id_segmento_min: int | None = None) -> list[dict]:
    """
    Uses store procedure dbo.usp_Tool2_FetchDiscardedSegments to obtain rows elegible for Tool 2 processing. They are returned in ascending order, and id_segmento_min should always be passed to avoid pulling the whole table
    """

    query = text(
        "EXEC dbo.usp_Tool2_FetchDiscardedSegments @IdSegmentoMin = :id_segmento_min"
    )

    with engine.connect() as conn:
        rows = (
            conn.execute(query, {"id_segmento_min": id_segmento_min}).mappings().all()
        )
    return [dict(row) for row in rows]


def segment_already_recorded(id_segmento: int) -> bool:
    """
    Checks if ID_SEGMENTO already has at least one row in MENCIONES_COMERCIALES table. This protects in case the segment's checkpoint was written but the process died before exiting cleanly,  or a manual re-rum with an older checkpoint.
    """
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


_INSERT_MENCION_QUERY = text(
    """
    EXEC dbo.usp_Tool2_InsertMencionComercial
        @ID_SEGMENTO = :id_segmento, @ID_TESTIGO = :id_testigo,
        @ID_ESTATUS_SEGMENTO = :id_estatus_segmento, @TITULO = :titulo,
        @ANUNCIANTE = :anunciante, @MARCA = :marca,
        @NUM_ANUNC = :num_anunc, @NUM_MARCA = :num_marca,
        @INICIO_MENCION = :inicio_mencion, @FIN_MENCION = :fin_mencion,
        @TRANSCRIPCION = :transcripcion, @TRANSCRIPCION_COMPLETA = :transcripcion_completa
    """
)


def _mention_params(mentions: list[dict]) -> list[dict]:
    missing_link = [m for m in mentions if m.get("id_segmento") is None]
    if missing_link:
        raise ValueError(
            f"{len(missing_link)} mention(s) have no id_segmento -- call process() "
            "with the source `segment` row before saving"
        )

    return [
        {
            "id_segmento": m["id_segmento"],
            "id_testigo": m["id_testigo"],
            "id_estatus_segmento": m["id_estatus_segmento"],
            "titulo": m.get("titulo") or m.get("marca"),
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
    ]


def save_mentions(mentions: list[dict]) -> None:
    """
    Runs store procedure dbo.usp_Tool2_InsertMencionComercial to store brand mentions in the table. It stores one row per mention.
    """

    if not mentions:
        return

    params = _mention_params(mentions)
    with engine.connect() as conn:
        conn.execute(_INSERT_MENCION_QUERY, params)
        conn.commit()


def save_mentions_test(mentions: list[dict]) -> None:
    """
    Same as save_mentions() but writes to the db_test database, which must have the same MENCIONES_COMERCIALES table and dbo.usp_Tool2_InsertMencionComercial procedure deployed.
    """

    if not mentions:
        return

    if db_test is None:
        raise RuntimeError(
            "db_test is not configured -- set TEST_DB_SERVER_URL and TEST_DB_SERVER_DATABASE in .env"
        )

    params = _mention_params(mentions)
    with db_test.connect() as conn:
        conn.execute(_INSERT_MENCION_QUERY, params)
        conn.commit()


def current_max_id_segmento() -> int:
    """
    Returns the current maximum ID_SEGMENTO in the database.

    This is used to initialize the checkpoint file on the first run.
    """
    with engine.connect() as conn:
        return conn.execute(text("SELECT MAX(ID_SEGMENTO) FROM SEGMENTO_SARA")).scalar()
