import os

from src.audio import transcribe_audio_segments
from src.extraction import extract_spot_details
from src.segmentation import detect_blocks
from src.slicing import slice_audio

with open("output.txt", "w") as f:
    for file in os.listdir("input/"):
        f.write(file + "\n")
        if file.endswith(".wav") or file.endswith(".mp3"):
            audio_file = "input/" + file
            segments = transcribe_audio_segments(audio_file)
            blocks = detect_blocks(segments)
            block_paths = slice_audio(audio_file, blocks, "output_blocks/")

            for block, block_path in zip(blocks, block_paths):
                transcript = block["text"]
                extracted = extract_spot_details(transcript)

                f.write(f"  {block_path} [{block['start']:.1f}-{block['end']:.1f}s]\n")
                f.write(f"  transcript: {transcript}\n")
                f.write(f"  categoria: {extracted['categoria']}\n")
                f.write(f"  anunciante: {extracted['anunciante']}\n")
                f.write(f"  marca: {extracted['marca']}\n")
                f.write(f"  marca_corto: {extracted['marca_corto']}\n")
                f.write(f"  version: {extracted['version']}\n")
                f.write(f"  vigencia: {extracted['vigencia']}\n")
                f.write(f"  keywords: {extracted['keywords']}\n\n")
