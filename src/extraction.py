import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

SYSTEM_PROMPT = """You are helping a media monitoring company that tracks commercials on radio and TV.
You will be given the transcript of a short audio clip suspected to be a commercial.

Extract:
- "keywords": brand names, product names, and other commercial-relevant entities mentioned in the transcript.
- "name": a short label for the clip, formatted as "<Brand> - <product/category>" when a brand is clear,
  otherwise a short descriptive title of the topic.

Write all output text in Spanish (brand/product names should stay as mentioned in the transcript, but
any descriptive wording you generate for "name" or non-brand keywords must be in Spanish).

If the transcript is empty, too short, or too garbled to make sense of, return an empty "keywords" list
and set "name" to "Clip no identificado". Do not invent brands that are not actually mentioned.

Respond with JSON only, matching this shape:
{"keywords": ["..."], "name": "..."}
"""


def extract_keywords_and_name(transcript: str) -> dict:
    if not transcript or not transcript.strip():
        return {"keywords": [], "name": "Clip no identificado"}

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    data = json.loads(content or "{}")

    return {
        "keywords": data.get("keywords", []),
        "name": data.get("name", "Clip no identificado"),
    }
