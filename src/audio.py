import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def transcribe_audio(filepath: str) -> str:
    with open(filepath, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="json",
        )
    return result.text


def transcribe_audio_segments(filepath: str) -> list[dict]:
    with open(filepath, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    return [
        {
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip(),
        }
        for segment in result.segments
    ]
