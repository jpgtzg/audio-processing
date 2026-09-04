"""Read-only dry run of Tool 2's real pipeline on SaraAlt.

Pulls up to 10 discarded segments belonging to a single SARA host (default
sara3, the one confirmed reachable -- see docs/handoff.md "File access"),
crops + transcribes + runs brand-mention detection on each exactly like
src/tool2.py's process(), and writes the results to a .txt file.

Never calls save_mentions() -- no DB writes happen. Safe to run repeatedly
while MENCIONES_COMERCIALES still doesn't exist (DB write access is still
blocked, see docs/progress.md).

Usage: tool2_test.exe [hostname] [id_testigo_min] [limit] [output_path]
  hostname       defaults to sara3
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
from src.tool2 import TOOL2_ESTATUS_IDS, crop_segment, resolve_testigo_path

DEFAULT_HOSTNAME = "sara3"
DEFAULT_ID_TESTIGO_MIN = 21_000_000
DEFAULT_LIMIT = 10


def fetch_segments_for_host(
    hostname: str,
    limit: int = DEFAULT_LIMIT,
    id_testigo_min: int | None = DEFAULT_ID_TESTIGO_MIN,
    estatus_ids: list[int] = TOOL2_ESTATUS_IDS,
) -> list[dict]:
    """Same query as src/tool2.py's fetch_discarded_segments(), narrowed to one
    host and capped at `limit` rows so this stays a quick, cheap dry run."""
    query = text(
        f"""
        SELECT TOP {int(limit)}
               s.ID_SEGMENTO, s.ID_TESTIGO, s.ID_ESTATUS_SEGMENTO, s.INICIO, s.DURACION,
               t.HOSTNAME, t.ARCHIVO
        FROM SEGMENTO_SARA s
        JOIN TESTIGO_SARA t ON s.ID_TESTIGO = t.ID_TESTIGO
        WHERE s.ID_ESTATUS_SEGMENTO IN :estatus_ids
          AND UPPER(t.HOSTNAME) = UPPER(:hostname)
          AND (:id_testigo_min IS NULL OR s.ID_TESTIGO >= :id_testigo_min)
        ORDER BY s.ID_TESTIGO DESC
        """
    ).bindparams(bindparam("estatus_ids", expanding=True))

    with engine.connect() as conn:
        rows = (
            conn.execute(
                query,
                {
                    "estatus_ids": list(estatus_ids),
                    "hostname": hostname,
                    "id_testigo_min": id_testigo_min,
                },
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def process_segment(segment: dict) -> dict:
    """Same as src/tool2.py's process(), but returns the transcript alongside
    the mentions (instead of just mentions) so the .txt output can show both,
    and never touches the DB beyond the initial read."""
    testigo_path = resolve_testigo_path(segment["HOSTNAME"], segment["ARCHIVO"])
    clip_path = crop_segment(testigo_path, segment["INICIO"], segment["DURACION"])

    try:
        segments = transcribe_timestamped_segments(clip_path)
    finally:
        os.remove(clip_path)

    transcript = " ".join(s["text"] for s in segments)
    mentions = extract_brand_mentions(segments)
    return {"transcript": transcript, "mentions": mentions}


def main() -> None:
    hostname = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOSTNAME
    id_testigo_min = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_ID_TESTIGO_MIN
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_LIMIT
    output_path = (
        sys.argv[4]
        if len(sys.argv) > 4
        else f"tool2_test_results_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"
    )

    print(f"Fetching up to {limit} discarded segments for host '{hostname}' "
          f"(ID_TESTIGO >= {id_testigo_min})...")
    segments = fetch_segments_for_host(
        hostname, limit=limit, id_testigo_min=id_testigo_min
    )
    print(f"Found {len(segments)} segment(s). No DB writes will happen.")

    lines = [
        "Tool 2 read-only dry run",
        f"host={hostname} id_testigo_min={id_testigo_min} limit={limit}",
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

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nWrote results to {output_path}")


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
