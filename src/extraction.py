import json
import os
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import text

from src.db.db import engine

load_dotenv()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


@lru_cache(maxsize=1)
def get_categorias() -> list[str]:
    """CATEGORIA taxonomy, pulled live from SUBCAT3.TIT_SUB3 -- the bottom level of
    the client's 4-level CATEGORIAS -> SUBCAT1 -> SUBCAT2 -> SUBCAT3 hierarchy,
    which is what COMERCIALES.CVE_SUB3 (and this extraction's "categoria" field)
    actually hangs off. Cached per-process since the taxonomy changes rarely."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT TIT_SUB3 FROM SUBCAT3 ORDER BY TIT_SUB3")
        ).scalars().all()
    return list(rows)


def _build_system_prompt() -> str:
    categorias = get_categorias()
    return f"""You are helping a media monitoring company that tracks commercials on radio and TV.
You will be given the transcript of a short audio clip suspected to be a commercial, and must extract it
into the same fields the client already uses in their monitoring database, so the output can be merged
directly into their existing records.

Extract:
- "categoria": the single best-matching category for this clip, chosen from this exact list (copy the
  string exactly as written, including any trailing "*"): {json.dumps(categorias, ensure_ascii=False)}
  If truly nothing on the list fits (e.g. a station jingle with no commercial content), use null.
- "anunciante": the company/organization actually paying for and running the ad (e.g. "GRUPO H.E.B.",
  "GENERAL MOTORS"). If the transcript only gives a consumer-facing brand and the parent company isn't
  identifiable from it, reuse the brand name here.
- "marca": the full brand/product name as said in the transcript (e.g. "H.E.B. TIENDA DE AUTOSERVICIO").
- "marca_corto": a short version of the brand name (e.g. "H.E.B.", "CHEVROLET").
- "version": a short tag summarizing the spot's key promotional content (offer, price, tagline) in the
  style "<MARCA_CORTO> / <short highlight>", e.g. "COPPEL / 40% DESCUENTO LINEA BLANCA".
- "vigencia": the offer's validity/expiration date, ONLY if a specific date is explicitly stated in the
  transcript (e.g. "válido hasta el 19 de julio" -> "2026-07-19"). Otherwise null. Do not guess or infer
  a date that isn't spoken.
- "keywords": brand names, product names, and other commercial-relevant entities mentioned.

**A single commercial often lists several other brands' products as part of its own pitch** — a supermarket
or department-store spot listing weekly discounts will rattle off product brands one after another (e.g.
"Colgate crema dental, Axion desodorante, Nivea crema líquida, todo con descuento"). Those listed products
are NOT the advertiser: the advertiser/marca is the store or business actually running and paying for the
spot (e.g. "SORIANA", "H.E.B."), even though it's never the loudest or most-repeated name in the audio. Do
not pick one of the listed product brands as "anunciante"/"marca" just because it's mentioned clearly or
often. Put the listed product brands in "keywords" instead — that's exactly what that field is for. If the
actual host/store name isn't stated in the transcript at all (the clip starts mid-list, for example), set
"anunciante"/"marca" to null rather than guessing one of the listed products.

Write all output text in Spanish (brand/product names should stay as mentioned in the transcript, but
any descriptive wording you generate must be in Spanish).

If the transcript is empty, too short, or too garbled to make sense of, set every field to null (empty
list for "keywords") instead of inventing a brand or category. Do not invent brands that are not actually
mentioned.

Respond with JSON only, matching this shape:
{{"categoria": "...", "anunciante": "...", "marca": "...", "marca_corto": "...", "version": "...",
"vigencia": "...", "keywords": ["..."]}}
"""

_EMPTY_RESULT = {
    "categoria": None,
    "anunciante": None,
    "marca": None,
    "marca_corto": None,
    "version": None,
    "vigencia": None,
    "keywords": [],
}


def extract_spot_details(transcript: str) -> dict:
    if not transcript or not transcript.strip():
        return dict(_EMPTY_RESULT)

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": transcript},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    data = json.loads(content or "{}")

    return {
        "categoria": data.get("categoria"),
        "anunciante": data.get("anunciante"),
        "marca": data.get("marca"),
        "marca_corto": data.get("marca_corto"),
        "version": data.get("version"),
        "vigencia": data.get("vigencia"),
        "keywords": data.get("keywords", []),
    }


BRAND_MENTION_SYSTEM_PROMPT = """You are helping a media monitoring company scan discarded/oversized audio
segments from a TV or radio program (song breaks, operator chatter, long unclassified stretches — NOT
confirmed commercials) for any mention of a brand or advertiser, so a capturista can review whether it's
worth investigating further.

You will be given a transcript as a numbered list of timestamped segments, e.g.:
[0] 0.00-2.40: "..."
[1] 2.40-5.10: "..."

Find every distinct brand/advertiser mention. For each one, report:
- "marca": the brand/product name as said.
- "anunciante": the company behind it, if identifiable from the mention; otherwise reuse "marca".
- "start_segment" / "end_segment": the indices (from the numbered list) of the first and last segment the
  mention spans. Use the same index for both if it's contained in one segment.

Do not invent mentions. If the transcript is just music, silence, or unrelated chatter with no brand
mentioned, return an empty list. A brief passing mention still counts.

Write all output text in Spanish (brand/product names should stay as mentioned in the transcript).

Respond with JSON only, matching this shape:
{"mentions": [{"marca": "...", "anunciante": "...", "start_segment": 0, "end_segment": 0}]}
"""


def extract_brand_mentions(segments: list[dict]) -> list[dict]:
    """Given timestamped transcript segments (as returned by
    audio.transcribe_audio_segments), finds brand/advertiser mentions and resolves
    each one's segment-index span back to real start/end times in seconds."""
    if not segments:
        return []

    numbered = "\n".join(
        f"[{i}] {s['start']:.2f}-{s['end']:.2f}: \"{s['text']}\""
        for i, s in enumerate(segments)
    )

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": BRAND_MENTION_SYSTEM_PROMPT},
            {"role": "user", "content": numbered},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    data = json.loads(content or "{}")

    mentions = []
    for mention in data.get("mentions", []):
        start_idx = mention.get("start_segment")
        end_idx = mention.get("end_segment")
        if not isinstance(start_idx, int) or not isinstance(end_idx, int):
            continue
        if not (0 <= start_idx < len(segments) and 0 <= end_idx < len(segments)):
            continue
        mentions.append(
            {
                "marca": mention.get("marca"),
                "anunciante": mention.get("anunciante"),
                "start": segments[start_idx]["start"],
                "end": segments[end_idx]["end"],
            }
        )

    return mentions
