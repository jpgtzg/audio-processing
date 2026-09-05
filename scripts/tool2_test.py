"""Read-only dry run of Tool 2's real pipeline on SaraAlt.

Pulls up to `limit` discarded segments belonging to one or more SARA hosts
(default sara3, the one confirmed reachable -- see docs/handoff.md "File
access"), crops + transcribes + runs brand-mention detection on each exactly
like src/tool2.py's process(), and writes the results to a .txt file.

Never calls save_mentions() -- no DB writes happen. Safe to run repeatedly
while MENCIONES_COMERCIALES still doesn't exist (DB write access is still
blocked, see docs/progress.md).

Usage: tool2_test.exe [hostnames] [id_testigo_min] [limit] [output_path]
  hostnames      defaults to sara3. Comma-separated for several hosts (e.g.
                  "sara3,sara13"), or "all" to match src/tool2.py's real
                  production scope -- it has no host filter at all.
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
    TESTIGO_SHARE_TEMPLATE,
    TOOL2_ESTATUS_IDS,
    TOOL2_TESTIGO_ESTATUS_IDS,
    crop_segment,
    resolve_testigo_path,
)

DEFAULT_HOSTNAMES = ["sara3"]
DEFAULT_ID_TESTIGO_MIN = 21_000_000
DEFAULT_LIMIT = 10


def fetch_segments_for_host(
    hostnames: list[str] | None,
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

    hostnames=None matches every host, same as src/tool2.py's real
    production scope (it has no host filter at all) -- pass an explicit list
    to narrow a dry run to specific hosts, e.g. only the ones confirmed
    reachable so far."""
    host_filter = "1 = 1" if hostnames is None else "UPPER(t.HOSTNAME) IN :hostnames"
    query = text(
        f"""
        WITH ranked AS (
            SELECT s.ID_SEGMENTO, s.ID_TESTIGO, s.ID_ESTATUS_SEGMENTO, s.INICIO, s.DURACION,
                   t.HOSTNAME, t.ARCHIVO, t.CANAL,
                   ROW_NUMBER() OVER (PARTITION BY s.ID_TESTIGO ORDER BY s.INICIO) AS rn
            FROM SEGMENTO_SARA s
            JOIN TESTIGO_SARA t ON s.ID_TESTIGO = t.ID_TESTIGO
            WHERE s.ID_ESTATUS_SEGMENTO IN :estatus_ids
              AND t.ID_ESTATUS_TESTIGO IN :testigo_estatus_ids
              AND {host_filter}
              AND (:id_testigo_min IS NULL OR s.ID_TESTIGO >= :id_testigo_min)
        )
        SELECT TOP {int(limit)}
               ID_SEGMENTO, ID_TESTIGO, ID_ESTATUS_SEGMENTO, INICIO, DURACION, HOSTNAME, ARCHIVO, CANAL
        FROM ranked
        WHERE rn = 1
        ORDER BY ID_TESTIGO DESC
        """
    ).bindparams(
        bindparam("estatus_ids", expanding=True),
        bindparam("testigo_estatus_ids", expanding=True),
        *([bindparam("hostnames", expanding=True)] if hostnames is not None else []),
    )

    params = {
        "estatus_ids": list(estatus_ids),
        "testigo_estatus_ids": list(testigo_estatus_ids),
        "id_testigo_min": id_testigo_min,
    }
    if hostnames is not None:
        params["hostnames"] = [h.upper() for h in hostnames]

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().all()
    return [dict(row) for row in rows]


def process_segment(segment: dict) -> dict:
    """Same as src/tool2.py's process(), but returns the transcript alongside
    the mentions (instead of just mentions) so the .txt output can show both,
    and never touches the DB beyond the initial read."""
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
    return {"transcript": transcript, "mentions": mentions}


def diagnose_missing_file(segment: dict) -> str:
    r"""When resolve_testigo_path()'s path 404s, checks two alternate
    constructions to tell a path-resolution bug apart from a file that's
    genuinely gone from the live share (e.g. rotated/deleted since the
    OrbitMedia_Test snapshot was taken): (a) the pre-2026-09-03 layout that
    appended ARCHIVO onto \\<host>\sara\mp3 (double "mp3"), and (b) whether
    the share root itself is even listable."""
    hostname, archivo = segment["HOSTNAME"], segment["ARCHIVO"]
    share_root = TESTIGO_SHARE_TEMPLATE.format(hostname=hostname.lower())
    old_style_path = os.path.join(share_root, "mp3", archivo)

    if not os.path.isdir(share_root):
        return f"share root {share_root} itself is not reachable"

    if os.path.isfile(old_style_path):
        return f"FOUND at old-style path {old_style_path} -- path fix regressed this, needs revisiting"

    return (
        f"not found under either the current path or {old_style_path} -- "
        f"likely genuinely missing from the live share (stale DB snapshot), "
        f"not a path bug"
    )


def main() -> None:
    hostnames_arg = sys.argv[1] if len(sys.argv) > 1 else ",".join(DEFAULT_HOSTNAMES)
    hostnames = None if hostnames_arg.lower() == "all" else hostnames_arg.split(",")
    id_testigo_min = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_ID_TESTIGO_MIN
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_LIMIT
    output_path = (
        sys.argv[4]
        if len(sys.argv) > 4
        else f"tool2_test_results_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"
    )

    host_label = "all hosts" if hostnames is None else ", ".join(hostnames)
    print(f"Fetching up to {limit} discarded segments for {host_label} "
          f"(ID_TESTIGO >= {id_testigo_min})...")
    segments = fetch_segments_for_host(
        hostnames, limit=limit, id_testigo_min=id_testigo_min
    )
    print(f"Found {len(segments)} segment(s). No DB writes will happen.")

    lines = [
        "Tool 2 read-only dry run",
        f"hosts={host_label} id_testigo_min={id_testigo_min} limit={limit}",
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
            diag = diagnose_missing_file(segment)
            print(f"  SKIPPED -- recording not reachable: {e}")
            print(f"  DIAGNOSTIC: {diag}")
            lines.append(f"  SKIPPED -- recording not reachable: {e}")
            lines.append(f"  DIAGNOSTIC: {diag}")
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
