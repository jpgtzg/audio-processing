import os

LAST_ID_SEGMENTO_FILE = "tool2_last_id_segmento.txt"
POLL_INTERVAL_SECONDS = 3600
MAX_WORKERS = int(os.environ.get("TOOL2_MAX_WORKERS", str(5)))
