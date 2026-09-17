"""Read-only dry run of Tool 2's real pipeline on SaraAlt.

Pulls up to `limit` discarded segments (optionally narrowed to stations whose
ARCHIVO/callsign matches a given filter), crops + transcribes + runs
brand-mention detection on each exactly like src/tool2.py's process(), and
writes the results to a .txt file.

Never calls save_mentions() -- no DB writes happen. Safe to run repeatedly
while MENCIONES_COMERCIALES still doesn't exist (DB write access is still
blocked, see docs/progress.md).

DEBUG (temporary, 2026-09-09): every detected mention also gets its exact
audio span *and* a padded surrounding-context clip cut out and saved locally
under DEBUG_MENTIONS_DIR (see src/tool2.py), so a detection can be judged by
ear -- including whether the music actually ducks down for a real ad read --
rather than trusted from the transcript alone.

Usage: tool2_test.exe [stations] [id_testigo_min] [limit] [output_path]
  stations       defaults to "all" (matches src/tool2.py's real production
                  scope -- no station filter beyond EMISORAS_MENCION opt-in).
                  Pass a callsign substring (e.g. "XHLUPE") to narrow a dry
                  run to one station being piloted -- matched against
                  TESTIGO_SARA.ARCHIVO, comma-separated for several.
  id_testigo_min defaults to 21000000 (recent testigos only -- SEGMENTO_SARA
                  is 100M+ rows, always bound the scan)
  limit          defaults to 10
  output_path    defaults to tool2_test_results_<timestamp>.txt
"""

import datetime
import os
import sys

from sqlalchemy import bindparam, text

from src.audio import transcribe_timestamped_segments
from src.db.db import engine
from src.extraction import extract_brand_mentions
from src.tool2 import (
    TOOL2_ESTATUS_IDS,
    TOOL2_TESTIGO_ESTATUS_IDS,
    crop_segment,
    save_mention_debug_clips,
)

DEFAULT_STATIONS = None
DEFAULT_ID_TESTIGO_MIN = 21_000_000
DEFAULT_LIMIT = 10


def fetch_segments(
    stations: list[str] | None,
    limit: int = DEFAULT_LIMIT,
    id_testigo_min: int | None = DEFAULT_ID_TESTIGO_MIN,
    estatus_ids: list[int] = TOOL2_ESTATUS_IDS,
    testigo_estatus_ids: list[int] = TOOL2_TESTIGO_ESTATUS_IDS,
) -> list[dict]:
    """Same query as src/tool2.py's fetch_discarded_segments(), capped at
    `limit` distinct *testigos* (one segment each) rather than `limit`
    segments -- SEGMENTO_SARA has many segments per testigo, so capping on
    segments alone tends to sample the same handful of source files
    repeatedly instead of a diverse set worth checking file-by-file.

    stations=None matches every EMISORAS_MENCION-opted-in station, same as
    src/tool2.py's real production scope -- pass an explicit list of callsign
    substrings (matched against TESTIGO_SARA.ARCHIVO) to narrow a dry run to
    one station being piloted, e.g. the client's XHLUPE test case."""
    station_filter = (
        "1 = 1"
        if stations is None
        else "(" + " OR ".join(f"t.ARCHIVO LIKE :station_{i}" for i in range(len(stations))) + ")"
    )
    query = text(
        rf"""
        WITH ranked AS (
            SELECT s.ID_SEGMENTO, s.ID_TESTIGO, s.ID_ESTATUS_SEGMENTO, s.INICIO, s.DURACION,
                   t.CANAL, t.ARCHIVO,
                   '\\' + ho.NOM_HOST + '\' + mm.RUTA + '\' + mm.ARCHIVO AS RUTA,
                   ROW_NUMBER() OVER (PARTITION BY s.ID_TESTIGO ORDER BY s.INICIO) AS rn
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
              AND {station_filter}
              AND (:id_testigo_min IS NULL OR s.ID_TESTIGO >= :id_testigo_min)
        )
        SELECT TOP {int(limit)}
               ID_SEGMENTO, ID_TESTIGO, ID_ESTATUS_SEGMENTO, INICIO, DURACION, CANAL, ARCHIVO, RUTA
        FROM ranked
        WHERE rn = 1
        ORDER BY ID_TESTIGO DESC
        """
    ).bindparams(
        bindparam("estatus_ids", expanding=True),
        bindparam("testigo_estatus_ids", expanding=True),
    )

    params = {
        "estatus_ids": list(estatus_ids),
        "testigo_estatus_ids": list(testigo_estatus_ids),
        "id_testigo_min": id_testigo_min,
    }
    if stations is not None:
        for i, station in enumerate(stations):
            params[f"station_{i}"] = f"%{station.upper()}%"

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().all()
    return [dict(row) for row in rows]


def process_segment(segment: dict) -> dict:
    """Same as src/tool2.py's process(), but returns the transcript alongside
    the mentions (instead of just mentions) so the .txt output can show both,
    and never touches the DB beyond the initial read."""
    clip_path = crop_segment(
        segment["RUTA"], segment["INICIO"], segment["DURACION"], segment["CANAL"]
    )

    try:
        segments = transcribe_timestamped_segments(clip_path)
        transcript = " ".join(s["text"] for s in segments)
        mentions = extract_brand_mentions(segments)
        save_mention_debug_clips(segment["RUTA"], segment, mentions)
    finally:
        os.remove(clip_path)

    return {"transcript": transcript, "mentions": mentions}


def main() -> None:
    stations_arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    stations = None if stations_arg.lower() == "all" else stations_arg.split(",")
    id_testigo_min = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_ID_TESTIGO_MIN
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_LIMIT
    output_path = (
        sys.argv[4]
        if len(sys.argv) > 4
        else f"tool2_test_results_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"
    )

    station_label = "all opted-in stations" if stations is None else ", ".join(stations)
    print(f"Fetching up to {limit} discarded segments for {station_label} "
          f"(ID_TESTIGO >= {id_testigo_min})...")
    segments = fetch_segments(
        stations, limit=limit, id_testigo_min=id_testigo_min
    )
    print(f"Found {len(segments)} segment(s). No DB writes will happen.")

    lines = [
        "Tool 2 read-only dry run",
        f"stations={station_label} id_testigo_min={id_testigo_min} limit={limit}",
        f"generated {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        f"{len(segments)} segment(s) fetched",
        "=" * 60,
    ]

    for done, segment in enumerate(segments, start=1):
        label = (
            f"ID_SEGMENTO={segment['ID_SEGMENTO']} "
            f"ID_TESTIGO={segment['ID_TESTIGO']} ARCHIVO={segment['ARCHIVO']}"
        )
        print(f"[{done}/{len(segments)}] Processing {label}")
        lines.append(f"\n[{done}/{len(segments)}] {label}")

        try:
            result = process_segment(segment)
        except FileNotFoundError as e:
            print(f"  SKIPPED -- recording not reachable: {e}")
            lines.append(f"  SKIPPED -- recording not reachable: {e}")
            lines.append(f"  RUTA={segment['RUTA']}")
            continue
        except Exception as e:
            print(f"  ERROR -- {e}")
            lines.append(f"  ERROR -- {e}")
            continue

        lines.append(f"  transcript: {result['transcript']}")
        if not result["mentions"]:
            lines.append("  mentions: none")
        else:
            for mention in result["mentions"]:
                lines.append(
                    f"  mention: {mention.get('anunciante')} / {mention.get('marca')} "
                    f"({mention.get('start'):.2f}s-{mention.get('end'):.2f}s)"
                )
                lines.append(
                    f"    matched: NUM_ANUNC={mention.get('num_anunc')} "
                    f"(score={mention.get('anunciante_match_score')}) "
                    f"NUM_MARCA={mention.get('num_marca')} (score={mention.get('marca_match_score')})"
                )
                lines.append(f"    mention_transcript: {mention.get('mention_transcript')}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nWrote results to {output_path}")


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
