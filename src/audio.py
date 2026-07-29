import whisper

model = whisper.load_model("medium")


def transcribe_audio(filepath: str) -> str:
    result = model.transcribe(filepath)
    return str(result.get("text", ""))


def transcribe_audio_segments(filepath: str) -> list[dict]:
    result = model.transcribe(filepath)
    return [
        {
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"].strip(),
        }
        for segment in result.get("segments", [])
    ]
