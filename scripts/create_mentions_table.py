r"""One-off script: creates MENCIONES_COMERCIALES, Tool 2's output table, which
doesn't exist in the client's schema yet (see docs/progress.md). Idempotent --
safe to re-run; also adds any column in COLUMN_MIGRATIONS below that's missing
from an already-existing table (a prior run of this script, or the client's own
snapshot restore, may predate a given column).

Columns:
    ID_MENCION            identity PK
    ID_SEGMENTO/ID_TESTIGO source SEGMENTO_SARA row this mention came from
    ID_ESTATUS_SEGMENTO   which discard reason triggered detection -- see
                           src/tool2 TOOL2_ESTATUS_IDS (10 codes as of
                           2026-09-17, client-expanded from the original 3)
    MOTIVO_DESCARTE        human-readable version of ID_ESTATUS_SEGMENTO,
                           pulled live from CAT_ESTATUS_SEGMENTO.DESCRIPCION
                           (see src/tool2 get_motivo_descarte_labels()) so
                           this is readable without joining back to the catalog
    TITULO                 currently reuses MARCA (see src/tool2 save_mentions())
    ANUNCIANTE/MARCA       raw text Whisper extraction detected -- kept even when
                           NUM_ANUNC/NUM_MARCA below has no confident match, so a
                           capturista can still see/link the mention manually
    NUM_ANUNC/NUM_MARCA    fuzzy-matched ANUNCIANTES.NUM_ANUNC/MARCAS.NUM_MARCA IDs
                           (client-requested 2026-09-08; see src/extraction.py
                           match_anunciante()/match_marca()), NULL if no confident
                           match was found
    INICIO_MENCION/FIN_MENCION  mention span, in seconds within the clip
    TRANSCRIPCION          only the sentence(s) spanning the mention itself
                           (client-requested 2026-09-08 -- previously the whole
                           clip's transcript, repeated on every mention row)
    TRANSCRIPCION_COMPLETA the entire clip's transcript, kept alongside
                           TRANSCRIPCION for full context on review
    ID_ESTATUS_VALIDACION default 1 ("pending validation" -- no catalog table
                           backs this yet, mirrors ALTAS_SARA_FP's open question
                           about a "Pendiente de Validacion" status)
    FECHA_ALTA             defaults to now

No FK constraints to SEGMENTO_SARA/ANUNCIANTES/MARCAS -- test DB data isn't
guaranteed clean enough to enforce that safely from here.
"""

from sqlalchemy import text

from src.db.db import engine

CREATE_TABLE_SQL = """
CREATE TABLE MENCIONES_COMERCIALES (
    ID_MENCION INT IDENTITY(1,1) PRIMARY KEY,
    ID_SEGMENTO INT NOT NULL,
    ID_TESTIGO INT NOT NULL,
    ID_ESTATUS_SEGMENTO INT NOT NULL,
    MOTIVO_DESCARTE VARCHAR(200) NULL,
    TITULO VARCHAR(200) NULL,
    ANUNCIANTE VARCHAR(200) NULL,
    MARCA VARCHAR(200) NULL,
    NUM_ANUNC INT NULL,
    NUM_MARCA INT NULL,
    INICIO_MENCION NUMERIC(10,2) NOT NULL,
    FIN_MENCION NUMERIC(10,2) NOT NULL,
    TRANSCRIPCION VARCHAR(MAX) NULL,
    TRANSCRIPCION_COMPLETA VARCHAR(MAX) NULL,
    ID_ESTATUS_VALIDACION INT NOT NULL DEFAULT 1,
    FECHA_ALTA DATETIME NOT NULL DEFAULT GETDATE()
)
"""

# (column_name, ALTER TABLE statement to add it) -- applied in order to an
# already-existing table, skipping any column that's already there.
COLUMN_MIGRATIONS: list[tuple[str, str]] = [
    ("MOTIVO_DESCARTE", "ALTER TABLE MENCIONES_COMERCIALES ADD MOTIVO_DESCARTE VARCHAR(200) NULL"),
    ("NUM_ANUNC", "ALTER TABLE MENCIONES_COMERCIALES ADD NUM_ANUNC INT NULL"),
    ("NUM_MARCA", "ALTER TABLE MENCIONES_COMERCIALES ADD NUM_MARCA INT NULL"),
    ("TRANSCRIPCION_COMPLETA", "ALTER TABLE MENCIONES_COMERCIALES ADD TRANSCRIPCION_COMPLETA VARCHAR(MAX) NULL"),
]

# (column_name, target_length, ALTER TABLE statement) -- like COLUMN_MIGRATIONS
# but for widening a column that already exists and turned out too small once
# real data arrived, rather than adding a missing one. Only actually runs the
# ALTER when the column's current width is below target_length.
#
# MOTIVO_DESCARTE was VARCHAR(20), sized for the original 3 short hardcoded
# labels ("LOCUTOR"/"NOTICIERO"/"CANCION"). Since 2026-09-17 it's populated
# live from CAT_ESTATUS_SEGMENTO.DESCRIPCION instead (see src/tool2
# get_motivo_descarte_labels()), which runs up to 38 chars (e.g. "Descarte
# automático (Duracion Mínima)") -- caused a live "String or binary data
# would be truncated" INSERT failure the first time a long one came through.
COLUMN_WIDENINGS: list[tuple[str, int, str]] = [
    (
        "MOTIVO_DESCARTE",
        200,
        "ALTER TABLE MENCIONES_COMERCIALES ALTER COLUMN MOTIVO_DESCARTE VARCHAR(200) NULL",
    ),
]


def main():
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT OBJECT_ID('MENCIONES_COMERCIALES')")
        ).scalar()
        if exists is not None:
            added = []
            for column_name, alter_sql in COLUMN_MIGRATIONS:
                column_exists = conn.execute(
                    text(
                        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_NAME = 'MENCIONES_COMERCIALES' AND COLUMN_NAME = :column_name"
                    ),
                    {"column_name": column_name},
                ).scalar()
                if column_exists is None:
                    conn.execute(text(alter_sql))
                    added.append(column_name)

            widened = []
            for column_name, target_length, alter_sql in COLUMN_WIDENINGS:
                current_length = conn.execute(
                    text(
                        "SELECT CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_NAME = 'MENCIONES_COMERCIALES' AND COLUMN_NAME = :column_name"
                    ),
                    {"column_name": column_name},
                ).scalar()
                if current_length is not None and current_length < target_length:
                    conn.execute(text(alter_sql))
                    widened.append(column_name)

            if added or widened:
                conn.commit()
                if added:
                    print(f"MENCIONES_COMERCIALES already exists -- added columns: {', '.join(added)}.")
                if widened:
                    print(f"MENCIONES_COMERCIALES already exists -- widened columns: {', '.join(widened)}.")
            else:
                print("MENCIONES_COMERCIALES already exists, skipping.")
            return

        conn.execute(text(CREATE_TABLE_SQL))
        conn.commit()
        print("Created MENCIONES_COMERCIALES.")


if __name__ == "__main__":
    main()
