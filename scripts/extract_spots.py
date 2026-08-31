import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pymssql
from dotenv import load_dotenv

from src.db import SpotDetails

load_dotenv()

SERVER_URL = os.getenv("SERVER_URL")
DATABASE = os.getenv("DATABASE")
USERNAME = os.getenv("LOGIN")
PASSWORD = os.getenv("PASSWORD")
SERVER_PORT = os.getenv("PORT")

if not SERVER_URL or not DATABASE or not USERNAME or not PASSWORD or not SERVER_PORT:
    raise RuntimeError(
        "Missing required DB environment variables (SERVER_URL, DATABASE, LOGIN, PASSWORD, PORT)"
    )

os.environ["FREETDSCONF"] = os.path.join(os.path.dirname(__file__), "freetds.conf")

conn = pymssql.connect(
    server=SERVER_URL,
    port=SERVER_PORT,
    user=USERNAME,
    password=PASSWORD,
    database=DATABASE,
    timeout=20,
    login_timeout=15,
    as_dict=True,  # rows come back as dicts instead of tuples
)

cur = conn.cursor()
cur.execute("SELECT 1 AS ok")
rows = cur.fetchall()
print(rows)

# July 15th 2026
date = datetime(2026, 7, 15, 6, 0, tzinfo=ZoneInfo("America/Mexico_City"))
print(f"Date: {date.isoformat()}")

range_start = date.replace(hour=6, minute=0, second=0, microsecond=0, tzinfo=None)
range_end = date.replace(hour=13, minute=0, second=0, microsecond=0, tzinfo=None)

cur.execute(
    "SELECT a.ID_ALTAS_SARA_FP, a.ID_TESTIGO, a.VERSION, a.INICIO, a.DURACION, a.OFFSET_INI, a.OFFSET_FIN, a.ID_ESTATUS_ALTA, t.FECHA_INICIO FROM ALTAS_SARA_FP a JOIN TESTIGO_SARA t ON a.ID_TESTIGO = t.ID_TESTIGO WHERE t.ID_EMISORA = 24 AND t.FECHA_INICIO BETWEEN %s AND %s ORDER BY t.FECHA_INICIO, a.INICIO",
    (range_start, range_end),
)
rows = cur.fetchall()

spots: list[SpotDetails] = []

for row in rows:
    spots.append(
        SpotDetails(
            id_altas_sara_fp=row["ID_ALTAS_SARA_FP"],
            id_testigo=row["ID_TESTIGO"],
            version=row["VERSION"],
            inicio=row["INICIO"],
            duracion=row["DURACION"],
            offset_ini=row["OFFSET_INI"],
            offset_fin=row["OFFSET_FIN"],
            id_estatus_alta=row["ID_ESTATUS_ALTA"],
            fecha_inicio=row["FECHA_INICIO"],
        )
    )

import glob
import os

from pydub import AudioSegment

AUDIO_DIR = "client_data/Audios Completos XET-FM"
OUTPUT_DIR = "tool1_input"

os.makedirs(OUTPUT_DIR, exist_ok=True)

files = sorted(glob.glob(os.path.join(AUDIO_DIR, "*.mp3")))
print(f"Concatenating {len(files)} files: {[os.path.basename(f) for f in files]}")

combined = AudioSegment.empty()
for f in files:
    combined += AudioSegment.from_file(f)

for spot in spots:
    clip_start, clip_end = spot.compute_clip_times(range_start)
    clip = combined[clip_start * 1000 : clip_end * 1000]  # pydub slices in milliseconds

    filename = (
        f"XETFM_2026-07-15_alta{spot.id_altas_sara_fp}_dur{spot.duracion:.0f}.wav"
    )
    clip.export(os.path.join(OUTPUT_DIR, filename), format="wav")
    print(f"Wrote {filename} ({len(clip) / 1000:.1f}s)")
