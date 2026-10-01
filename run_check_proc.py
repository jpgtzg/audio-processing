"""PyInstaller entry point for a diagnostic that compares usp_Tool2_FetchDiscardedSegments
against the same query run inline, over the exact connection tool2.exe uses.

Usage: check_proc.exe [id_segmento_min]
"""

import sys

from sqlalchemy import text

from src.db.db import engine
from src.db.settings import settings

DEFAULT_ID_SEGMENTO_MIN = 171965098

INLINE_QUERY = """
SELECT s.ID_SEGMENTO, s.ID_TESTIGO, s.ID_ESTATUS_SEGMENTO, s.INICIO, s.DURACION,
       t.CANAL,
       '\\\\' + ho.NOM_HOST + '\\' + mm.RUTA + '\\' + mm.ARCHIVO AS RUTA
FROM SEGMENTO_SARA s
JOIN TESTIGO_SARA t ON s.ID_TESTIGO = t.ID_TESTIGO
JOIN EMISORAS_MENCION ee ON ee.ID_EMISORA = t.ID_EMISORA
JOIN MULTIMEDIA_ARCHIVO mua ON t.ID_MULTIMEDIA_ARCHIVO = mua.ID_MULTIMEDIA_ARCHIVO
JOIN MULTIMEDIA mm ON mm.ID_MULTIMEDIA_ARCHIVO = mua.ID_MULTIMEDIA_ARCHIVO AND mm.CANAL = 1
JOIN HOST ho ON mm.ID_HOST = ho.ID_HOST
WHERE s.ID_ESTATUS_SEGMENTO IN (10, 11, 12, 13, 14, 15, 16, 17, 18, 21)
  AND t.ID_ESTATUS_TESTIGO IN (10, 20)
  AND ee.MENCIONES = 1
  AND ee.FECHA_MENCION IS NOT NULL
  AND ee.FECHA_MENCION <= t.FECHA_INICIO
  AND s.ID_SEGMENTO >= :id_segmento_min
ORDER BY s.ID_SEGMENTO ASC
"""


def step(label: str, fn) -> None:
    try:
        print(f"{label}: {fn()}")
    except Exception as exc:  # diagnostic: keep going so every step reports
        print(f"{label}: FAILED -> {type(exc).__name__}: {exc}")


def main(argv: list[str]) -> None:
    id_min = int(argv[0]) if argv else DEFAULT_ID_SEGMENTO_MIN
    params = {"id_segmento_min": id_min}
    print(f"id_segmento_min = {id_min}")
    print(
        f"env: server={settings.DB_SERVER_URL} port={settings.DB_SERVER_PORT} "
        f"db={settings.DB_SERVER_DATABASE} login={settings.DB_LOGIN}"
    )

    with engine.connect() as conn:
        step(
            "connection identity (server, db, login, user, default schema)",
            lambda: tuple(
                conn.execute(
                    text(
                        "SELECT @@SERVERNAME, DB_NAME(), SUSER_SNAME(), USER_NAME(), SCHEMA_NAME()"
                    )
                ).one()
            ),
        )
        step(
            "proc found in sys.procedures (schema, modify_date)",
            lambda: [
                tuple(r)
                for r in conn.execute(
                    text(
                        "SELECT SCHEMA_NAME(schema_id), modify_date FROM sys.procedures "
                        "WHERE name = 'usp_Tool2_FetchDiscardedSegments'"
                    )
                )
            ],
        )
        step(
            "proc definition length",
            lambda: conn.execute(
                text(
                    "SELECT LEN(OBJECT_DEFINITION(OBJECT_ID('dbo.usp_Tool2_FetchDiscardedSegments')))"
                )
            ).scalar(),
        )
        step(
            "session options (ansi_nulls, quoted_identifier, concat_null_yields_null, arithabort)",
            lambda: tuple(
                conn.execute(
                    text(
                        "SELECT SESSIONPROPERTY('ANSI_NULLS'), SESSIONPROPERTY('QUOTED_IDENTIFIER'), "
                        "SESSIONPROPERTY('CONCAT_NULL_YIELDS_NULL'), SESSIONPROPERTY('ARITHABORT')"
                    )
                ).one()
            ),
        )
        step(
            "proc stored settings (uses_ansi_nulls, uses_quoted_identifier)",
            lambda: tuple(
                conn.execute(
                    text(
                        "SELECT uses_ansi_nulls, uses_quoted_identifier FROM sys.sql_modules "
                        "WHERE object_id = OBJECT_ID('dbo.usp_Tool2_FetchDiscardedSegments')"
                    )
                ).one()
            ),
        )
        step(
            "proc source:\n"
            + "-" * 60,
            lambda: "\n"
            + str(
                conn.execute(
                    text(
                        "SELECT OBJECT_DEFINITION(OBJECT_ID('dbo.usp_Tool2_FetchDiscardedSegments'))"
                    )
                ).scalar()
            )
            + "\n"
            + "-" * 60,
        )
        step(
            "A) EXEC proc via SQLAlchemy (what tool2 does) -> rows",
            lambda: len(
                conn.execute(
                    text(
                        "EXEC dbo.usp_Tool2_FetchDiscardedSegments @IdSegmentoMin = :id_segmento_min"
                    ),
                    params,
                )
                .mappings()
                .all()
            ),
        )
        step(
            "B) same query inline -> rows",
            lambda: len(conn.execute(text(INLINE_QUERY), params).all()),
        )

    def raw_exec() -> int:
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute(f"EXEC dbo.usp_Tool2_FetchDiscardedSegments @IdSegmentoMin = {id_min}")
            return len(cur.fetchall())
        finally:
            raw.close()

    step("C) EXEC proc via raw pymssql cursor, literal param -> rows", raw_exec)
    print("done")


if __name__ == "__main__":
    main(sys.argv[1:])
