r"""One-off script: creates MENCIONES_COMERCIALES, Tool 2's output table, which
doesn't exist in the client's schema yet (see docs/progress.md). Idempotent --
safe to re-run; also adds MOTIVO_DESCARTE to an already-existing table that
predates that column (see ADD_MOTIVO_DESCARTE_SQL below).

Columns:
    ID_MENCION            identity PK
    ID_SEGMENTO/ID_TESTIGO source SEGMENTO_SARA row this mention came from
    ID_ESTATUS_SEGMENTO   which discard reason triggered detection (locutor/
                           noticiero/cancion -- see src/tool2.py TOOL2_ESTATUS_IDS)
    MOTIVO_DESCARTE        human-readable version of ID_ESTATUS_SEGMENTO
                           ("LOCUTOR"/"NOTICIERO"/"CANCION") so this is readable
                           without joining back to a catalog table
    TITULO/ANUNCIANTE/MARCA, TRANSCRIPCION
    INICIO_MENCION/FIN_MENCION  mention span, in seconds within the clip
    ID_ESTATUS_VALIDACION default 1 ("pending validation" -- no catalog table
                           backs this yet, mirrors ALTAS_SARA_FP's open question
                           about a "Pendiente de Validacion" status)
    FECHA_ALTA             defaults to now

No FK constraints to SEGMENTO_SARA -- test DB data isn't guaranteed clean enough
to enforce that safely from here.
"""

from sqlalchemy import text

from src.db.db import engine

CREATE_TABLE_SQL = """
CREATE TABLE MENCIONES_COMERCIALES (
    ID_MENCION INT IDENTITY(1,1) PRIMARY KEY,
    ID_SEGMENTO INT NOT NULL,
    ID_TESTIGO INT NOT NULL,
    ID_ESTATUS_SEGMENTO INT NOT NULL,
    MOTIVO_DESCARTE VARCHAR(20) NULL,
    TITULO VARCHAR(200) NULL,
    ANUNCIANTE VARCHAR(200) NULL,
    MARCA VARCHAR(200) NULL,
    INICIO_MENCION NUMERIC(10,2) NOT NULL,
    FIN_MENCION NUMERIC(10,2) NOT NULL,
    TRANSCRIPCION VARCHAR(MAX) NULL,
    ID_ESTATUS_VALIDACION INT NOT NULL DEFAULT 1,
    FECHA_ALTA DATETIME NOT NULL DEFAULT GETDATE()
)
"""

ADD_MOTIVO_DESCARTE_SQL = """
ALTER TABLE MENCIONES_COMERCIALES ADD MOTIVO_DESCARTE VARCHAR(20) NULL
"""


def main():
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT OBJECT_ID('MENCIONES_COMERCIALES')")
        ).scalar()
        if exists is not None:
            column_exists = conn.execute(
                text(
                    "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = 'MENCIONES_COMERCIALES' AND COLUMN_NAME = 'MOTIVO_DESCARTE'"
                )
            ).scalar()
            if column_exists is None:
                conn.execute(text(ADD_MOTIVO_DESCARTE_SQL))
                conn.commit()
                print("MENCIONES_COMERCIALES already exists -- added MOTIVO_DESCARTE column.")
            else:
                print("MENCIONES_COMERCIALES already exists, skipping.")
            return

        conn.execute(text(CREATE_TABLE_SQL))
        conn.commit()
        print("Created MENCIONES_COMERCIALES.")


if __name__ == "__main__":
    main()
