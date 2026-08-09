import csv
import os

from src.audio import transcribe_audio
from src.extraction import extract_spot_details

INPUT_DIR = "tool1_input"
OUTPUT_PATH = "tool1_output.csv"

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


def main():
    files = sorted(f for f in os.listdir(INPUT_DIR) if f.endswith((".wav", ".mp3")))

    with open(OUTPUT_PATH, "w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDS)
        writer.writeheader()

        for filename in files:
            path = os.path.join(INPUT_DIR, filename)
            transcript = transcribe_audio(path)
            extracted = extract_spot_details(transcript)

            row = {
                "filename": filename,
                "transcript": transcript,
                "keywords": "; ".join(extracted["keywords"]),
                **{
                    k: extracted[k]
                    for k in FIELDS
                    if k not in ("filename", "transcript", "keywords")
                },
            }
            writer.writerow(row)
            print(f"{filename}: {extracted['anunciante']} / {extracted['marca_corto']}")


if __name__ == "__main__":
    main()
