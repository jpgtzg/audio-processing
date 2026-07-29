import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

SYSTEM_PROMPT = """You are helping a media monitoring company split a continuous radio/TV recording into
individual blocks: separate commercials, station IDs/jingles, and program promos.

You will be given a JSON list of transcribed segments, each with "start" and "end" times in seconds and
the spoken "text" for that segment, in chronological order.

Group consecutive segments into blocks whenever the topic clearly changes (e.g. a water-safety PSA ends
and a jobs announcement begins, or a commercial ends and a station jingle begins). Segments belonging to
the same commercial/announcement/jingle stay in the same block, even if it takes several segments to say
it. Do not split a single commercial into multiple blocks just because it has several sentences.

Respond with JSON only, matching this shape:
{"blocks": [{"start": 0.0, "end": 12.3, "text": "..."}, ...]}

"start" and "end" must exactly match the boundaries of the first and last segment included in that block
(reuse the given segment start/end values, do not invent new timestamps). "text" is the concatenation of
that block's segment texts. Blocks must be in chronological order and must not overlap.
"""


def detect_blocks(segments: list[dict]) -> list[dict]:
    if not segments:
        return []

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(segments, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    data = json.loads(content or "{}")
    return data.get("blocks", [])
