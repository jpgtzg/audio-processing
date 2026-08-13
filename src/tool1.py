import os
import re

from src.audio import transcribe_audio
from src.extraction import extract_spot_details

INPUT_DIR = "output/20260813_152558"

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


def natural_sort_key(filename: str) -> list:
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r"(\d+)", filename)
    ]


def process(filename: str) -> dict:
    path = os.path.join(INPUT_DIR, filename)
    transcript = transcribe_audio(path)

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
    files = sorted(
        (f for f in os.listdir(INPUT_DIR) if f.endswith((".wav", ".mp3"))),
        key=natural_sort_key,
    )

    total = len(files)

    for done, file in enumerate(files, start=1):
        print("=" * 40)
        print("Processing file:", file)
        result = process(file)
        print(f"Result for {file}: {result['transcript']}...")
        print(
            f"[{done}/{total}] {file}: {result['anunciante']} / {result['marca_corto']}F"
        )


if __name__ == "__main__":
    main()
