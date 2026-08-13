r"""One-off script: find which client_data/wav2 clips have a matching ALTAS_SARA_FP
row in the DB, and copy those into real_audio_db/ with a manifest.

Matching works off ALTAS_SARA_FP.DETALLE, which embeds the original network path
SARA wrote the wav to, e.g.:
    "El wav [\\SARA3\AltasFP\wavs\XEDAF_01-01-2026_061810_11.wav] Fue Autorizado"
The trailing "XEDAF_01-01-2026_061810_11.wav" is byte-for-byte the same filename
convention used in client_data/wav2, so it's an exact match key -- no need to parse
VERSION/date/time and fuzzy-match on it.
"""

import csv
import os
import re
import shutil

from sqlalchemy import text

from src.db.db import engine

WAV2_DIR = "client_data/wav2"
OUTPUT_DIR = "real_audio_db"
MANIFEST_PATH = os.path.join(OUTPUT_DIR, "manifest.csv")

# wav2 filenames observed spanning 01-08-2026 .. 07-08-2026
DATE_FROM = "20260801"
DATE_TO = "20260808"

DETALLE_FILENAME_RE = re.compile(r"wavs\\([^\\\]]+\.wav)\]")


def fetch_db_rows() -> dict[str, dict]:
    query = text(
        """
        SELECT ID_ALTAS_SARA_FP, VERSION, INICIO, DURACION, OFFSET_INI, OFFSET_FIN,
               ID_ESTATUS_ALTA, ID_TESTIGO, DETALLE
        FROM ALTAS_SARA_FP
        WHERE DETALLE LIKE '%.wav]%'
          AND FECHA_ALTA >= :date_from
          AND FECHA_ALTA < :date_to
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(query, {"date_from": DATE_FROM, "date_to": DATE_TO}).mappings().all()

    by_filename = {}
    for row in rows:
        match = DETALLE_FILENAME_RE.search(row["DETALLE"])
        if match:
            by_filename[match.group(1)] = row
    return by_filename


def main():
    wav2_files = sorted(f for f in os.listdir(WAV2_DIR) if f.endswith(".wav"))
    print(f"wav2 files on disk: {len(wav2_files)}")

    db_rows = fetch_db_rows()
    print(f"ALTAS_SARA_FP rows with a wav filename in range: {len(db_rows)}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    matched = [f for f in wav2_files if f in db_rows]
    print(f"matched: {len(matched)} / {len(wav2_files)}")

    with open(MANIFEST_PATH, "w", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(
            [
                "filename",
                "id_altas_sara_fp",
                "id_testigo",
                "version",
                "inicio_ms",
                "duracion_s",
                "offset_ini",
                "offset_fin",
                "id_estatus_alta",
            ]
        )
        for filename in matched:
            row = db_rows[filename]
            shutil.copy2(
                os.path.join(WAV2_DIR, filename), os.path.join(OUTPUT_DIR, filename)
            )
            writer.writerow(
                [
                    filename,
                    row["ID_ALTAS_SARA_FP"],
                    row["ID_TESTIGO"],
                    row["VERSION"],
                    row["INICIO"],
                    row["DURACION"],
                    row["OFFSET_INI"],
                    row["OFFSET_FIN"],
                    row["ID_ESTATUS_ALTA"],
                ]
            )

    print(f"Wrote {len(matched)} files + manifest to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
