import os

from pydub import AudioSegment


def slice_audio(filepath: str, blocks: list[dict], output_dir: str) -> list[str]:
    os.makedirs(output_dir, exist_ok=True)
    audio = AudioSegment.from_file(filepath)
    base_name = os.path.splitext(os.path.basename(filepath))[0]

    output_paths = []
    for i, block in enumerate(blocks):
        start_ms = int(block["start"] * 1000)
        end_ms = int(block["end"] * 1000)
        clip = audio[start_ms:end_ms]

        output_path = os.path.join(output_dir, f"{base_name}_block{i:02d}.wav")
        clip.export(output_path, format="wav")
        output_paths.append(output_path)

    return output_paths
