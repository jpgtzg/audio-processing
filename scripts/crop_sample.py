"""Grabs 5 random clips from client_data/real_audio_db, crops each to its
INICIO/DURACION window (per manifest.csv), and writes them to output/{datetime}/ so
they can be listened to and checked for being cut short."""

import csv
import os
import random
from datetime import datetime

from pydub import AudioSegment

INPUT_DIR = "client_data/real_audio_db"
MANIFEST_PATH = os.path.join(INPUT_DIR, "manifest.csv")
OUTPUT_ROOT = "output"
SAMPLE_SIZE = 5


def main():
    with open(MANIFEST_PATH, newline="") as f:
        rows = list(csv.DictReader(f))

    sample = random.sample(rows, SAMPLE_SIZE)

    output_dir = os.path.join(OUTPUT_ROOT, datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(output_dir, exist_ok=True)

    for row in sample:
        filename = row["filename"]
        inicio_ms = int(row["inicio_ms"])
        duracion_s = int(row["duracion_s"])

        audio = AudioSegment.from_file(os.path.join(INPUT_DIR, filename))
        crop = audio[inicio_ms : inicio_ms + duracion_s * 1000]

        out_path = os.path.join(output_dir, filename)
        crop.export(out_path, format="wav")
        print(f"{filename}: cropped {len(crop) / 1000:.1f}s -> {out_path}")

    print(f"\nWrote {len(sample)} clips to {output_dir}/")


if __name__ == "__main__":
    main()
