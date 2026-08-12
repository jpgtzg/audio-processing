import csv
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import text

from src.audio import transcribe_audio
from src.db.db import engine
from src.extraction import extract_spot_details

INPUT_DIR = "client_data/wav2"
OUTPUT_PATH = "tool1_output.csv"
MAX_WORKERS = 8

# Whisper's `prompt` only biases decoding using roughly its last 224 tokens, so this
# stays short: the advertiser names that actually air most in this market/date range,
# ranked by frequency, to bias Whisper toward the correct spelling instead of a
# phonetic guess (e.g. "CHEDRAUI" instead of "CHEDRAGUI").
VOCAB_PROMPT_MAX_CHARS = 900


def build_vocabulary_prompt() -> str:
    query = text("""
        SELECT TOP 80 an.TIT_ANUNC, COUNT(*) as cnt
        FROM ALTAS_SARA_FP a
        JOIN TESTIGO_SARA t ON a.ID_TESTIGO = t.ID_TESTIGO
        LEFT JOIN FINGERPRINT fp ON a.ID_FP_IMG = fp.ID_FP
        LEFT JOIN ANUNCIANTES an ON fp.ID_ANUNCIANTE = an.NUM_ANUNC
        WHERE t.FECHA_INICIO BETWEEN '20260801' AND '20260808' AND an.TIT_ANUNC IS NOT NULL
        GROUP BY an.TIT_ANUNC
        ORDER BY cnt DESC
    """)
    with engine.connect() as conn:
        names = [row.TIT_ANUNC for row in conn.execute(query)]

    prompt = ""
    for name in names:
        candidate = f"{prompt}, {name}" if prompt else name
        if len(candidate) > VOCAB_PROMPT_MAX_CHARS:
            break
        prompt = candidate
    return prompt


FIELDS = [
    "filename",
    "categoria",
    "anunciante",
    "marca",
    "version",
    "keywords",
    "marca_corto",
    "vigencia",
    "transcript",
]


def process(filename: str, vocab_prompt: str) -> dict:
    path = os.path.join(INPUT_DIR, filename)
    transcript = transcribe_audio(path, prompt=vocab_prompt)
    extracted = extract_spot_details(transcript)

    return {
        "filename": filename,
        "transcript": transcript,
        "keywords": "; ".join(extracted["keywords"]),
        **{
            k: extracted[k]
            for k in FIELDS
            if k not in ("filename", "transcript", "keywords")
        },
    }


def main():
    files = sorted(f for f in os.listdir(INPUT_DIR) if f.endswith((".wav", ".mp3")))
    total = len(files)
    write_lock = threading.Lock()

    vocab_prompt = build_vocabulary_prompt()
    print(f"vocab prompt ({len(vocab_prompt)} chars): {vocab_prompt}")

    with open(OUTPUT_PATH, "w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDS)
        writer.writeheader()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(process, filename, vocab_prompt): filename for filename in files
            }

            for done, future in enumerate(as_completed(futures), start=1):
                filename = futures[future]
                try:
                    row = future.result()
                except Exception as exc:
                    print(f"[{done}/{total}] {filename}: FAILED ({exc})")
                    continue

                with write_lock:
                    writer.writerow(row)
                    out.flush()
                print(f"[{done}/{total}] {filename}: {row['anunciante']} / {row['marca_corto']}")


if __name__ == "__main__":
    main()
