import os

from audio import transcribe_audio_segments
from extraction import extract_keywords_and_name
from segmentation import detect_blocks
from slicing import slice_audio

with open("output.txt", "w") as f:
    for file in os.listdir("input/"):
        f.write(file + "\n")
        if file.endswith(".wav"):
            audio_file = "input/" + file
            segments = transcribe_audio_segments(audio_file)
            blocks = detect_blocks(segments)
            block_paths = slice_audio(audio_file, blocks, "output_blocks/")

            for block, block_path in zip(blocks, block_paths):
                transcript = block["text"]
                extracted = extract_keywords_and_name(transcript)

                f.write(f"  {block_path} [{block['start']:.1f}-{block['end']:.1f}s]\n")
                f.write(f"  transcript: {transcript}\n")
                f.write(f"  name: {extracted['name']}\n")
                f.write(f"  keywords: {extracted['keywords']}\n\n")
