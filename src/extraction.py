import json
import os
import re
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI
from rapidfuzz import fuzz, process as fuzzy_process
from sqlalchemy import text

from src.db.db import engine

load_dotenv()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

ANUNCIANTE_MATCH_THRESHOLD = float(os.environ.get("ANUNCIANTE_MATCH_THRESHOLD", 88))
MARCA_MATCH_THRESHOLD = float(os.environ.get("MARCA_MATCH_THRESHOLD", 90))


def _fuzzy_match_key(s: str) -> str:
    """Normalizes a string for fuzzy matching: uppercase, punctuation/whitespace
    stripped entirely (not replaced with spaces -- rapidfuzz's own
    utils.default_process replaces punctuation with spaces, which drags down
    scores for abbreviations like "H.E.B" vs "HEB"). Also required just to get
    case-insensitivity at all: rapidfuzz's scorers are case-sensitive at the
    character level, so "Soriana" vs the catalog's "SORIANA" would otherwise
    score as if 6 of 7 letters differ."""
    return re.sub(r"[^A-Z0-9]", "", s.upper())


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


@lru_cache(maxsize=1)
def get_anunciantes() -> list[dict]:
    """ANUNCIANTES catalog (15k+ rows) -- too large to hand to an LLM as a closed
    list the way get_categorias()/get_marcas() are, so this backs fuzzy matching
    (match_anunciante()) instead. Cached per-process; the catalog changes rarely
    relative to a single run."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT NUM_ANUNC, TIT_ANUNC, ABREV_ANUNC FROM ANUNCIANTES")
        ).mappings().all()
    return [dict(row) for row in rows]


@lru_cache(maxsize=1)
def get_marcas() -> list[dict]:
    """MARCAS catalog -- small enough (581 rows) to fuzzy-match directly, same
    approach as get_anunciantes(). Cached per-process."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT NUM_MARCA, TIT_MARCA FROM MARCAS")
        ).mappings().all()
    return [dict(row) for row in rows]


def match_anunciante(detected: str | None) -> tuple[int | None, float | None]:
    """Fuzzy-matches a detected advertiser name against ANUNCIANTES.TIT_ANUNC and
    ABREV_ANUNC (whichever scores higher), returning (NUM_ANUNC, score) or
    (None, None) if nothing clears ANUNCIANTE_MATCH_THRESHOLD -- e.g. a real but
    uncatalogued local advertiser. Caller should keep the raw detected text
    around even on a miss, for manual linking later.

    Uses plain fuzz.ratio (not WRatio) -- WRatio's partial-ratio component is
    too generous against a 15k-row catalog: a long, generic detected phrase can
    score 85+ against an unrelated catalog entry purely from sharing one common
    word (verified against real ANUNCIANTES rows). Plain ratio penalizes that
    kind of mismatch far more, at the cost of being stricter about close-but-
    not-exact real matches -- an acceptable trade since a missed match just
    stays NULL with the raw text preserved, while a wrong auto-assigned ID
    could misattribute a mention to an unrelated real company."""
    if not detected or not detected.strip():
        return None, None

    anunciantes = get_anunciantes()
    tit_candidates = {r["NUM_ANUNC"]: r["TIT_ANUNC"] for r in anunciantes if r["TIT_ANUNC"]}
    abrev_candidates = {r["NUM_ANUNC"]: r["ABREV_ANUNC"] for r in anunciantes if r["ABREV_ANUNC"]}

    best = None
    for candidates in (tit_candidates, abrev_candidates):
        match = fuzzy_process.extractOne(
            detected, candidates, scorer=fuzz.ratio, processor=_fuzzy_match_key
        )
        if match is not None and (best is None or match[1] > best[1]):
            best = match

    if best is None or best[1] < ANUNCIANTE_MATCH_THRESHOLD:
        return None, None
    _, score, num_anunc = best
    return num_anunc, score


def match_marca(detected: str | None) -> tuple[int | None, float | None]:
    """Fuzzy-matches a detected brand name against MARCAS.TIT_MARCA.

    Unlike match_anunciante(), uses fuzz.partial_ratio, not plain ratio --
    MARCAS entries often carry a "GRUPO X" company-level prefix around the
    actual brand name (e.g. "GRUPO COCA COLA", "GRUPO CHEVROLET DEL RIO
    AGENCI"), which plain ratio penalizes heavily for the length mismatch even
    on an exact brand match. MARCAS is small (581 rows, verified no candidate
    shorter than "BMW"/3 chars) so partial_ratio's usual risk of matching a
    short candidate as a trivial substring of anything is much lower here than
    it would be against the 15k-row ANUNCIANTES catalog -- kept at a higher
    threshold than match_anunciante() as extra safety margin regardless."""
    if not detected or not detected.strip():
        return None, None

    marcas = get_marcas()
    candidates = {r["NUM_MARCA"]: r["TIT_MARCA"] for r in marcas if r["TIT_MARCA"]}
    match = fuzzy_process.extractOne(
        detected, candidates, scorer=fuzz.partial_ratio, processor=_fuzzy_match_key
    )
    if match is None or match[1] < MARCA_MATCH_THRESHOLD:
        return None, None
    _, score, num_marca = match
    return num_marca, score


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

**Do not report the radio/TV station itself** — its own name, call sign, frequency (e.g. "88.9 FM"),
slogans, social media handles, or presenter/show names are self-promotion, not a commercial brand or
advertiser, even if repeated constantly. Only report brands that are distinct from the station running
the broadcast, i.e. something a real advertiser is paying to promote.

**Also do not report other programs, newscasts, or syndicated content brands announced as part of the
broadcast itself** — e.g. a syndicated newscast's own name ("Noticias Caracol", "El Financiero") said as
programming identification ("los dejamos con el reporte de Noticias Caracol"). Even though these may be
real, distinct companies, mentioning them this way is content credit/identification, not a commercial —
they aren't paying to advertise a product or service in this clip. Only report a company/brand when the
transcript is actually pitching or promoting something (a product, service, offer, or business), not just
naming a program or content source.

**The station promoting its own app, website, ad-sales product, or any other product/service it owns is
still self-promotion, not a commercial** — e.g. a station inviting listeners to download "its" app, or
pitching its own ad-buying product to potential advertisers ("anúnciate con nosotros a través de nuestro
InstaSpot"). Only report a mention when the transcript makes clear a *different*, external business is
the one being promoted or is paying for the spot.

**Strong signal to check first**: if the speaker uses first-person possessive language about the
product/app/service — "nuestra aplicación", "nuestro InstaSpot", "descarga nuestra app", "anúnciate con
nosotros", "nos escuchamos en", "nuestra página web" — that is the host/station referring to their own
thing. Treat this as conclusive proof of self-promotion and exclude it, no matter how distinct or
official-sounding the product's own name is (a station's own app or ad-sales product can absolutely have
its own brand name, like "Grupo Az" or "InstaSpot", while still being 100% self-promotion).

**Ignore known Whisper transcription-hallucination artifacts — never report these as brand mentions**:
stock phrases like "Subtítulos realizados/creados por la comunidad de Amara.org", "www.alimmenta.com" /
"Más información en www.alimmenta.com", generic YouTube-style outros ("suscríbete al canal", "like,
comment, and subscribe", "gracias por ver"), or any string of nonsense/mismatched-language fragments and
repeated "?" characters. These are transcription noise that shows up on silence, music, or low-confidence
audio — they are not something anyone actually said in this clip, regardless of how they're phrased.

Write all output text in Spanish (brand/product names should stay as mentioned in the transcript).

Respond with JSON only, matching this shape:
{"mentions": [{"marca": "...", "anunciante": "...", "start_segment": 0, "end_segment": 0}]}
"""


def extract_brand_mentions(segments: list[dict]) -> list[dict]:
    """Given timestamped transcript segments (as returned by
    audio.transcribe_timestamped_segments), finds brand/advertiser mentions and resolves
    each one's segment-index span back to real start/end times in seconds.

    Client-requested (2026-09-08): "mention_transcript" carries only the sentence(s)
    spanning start_segment..end_segment, not the whole clip's transcript -- previously
    every mention from the same segment repeated the entire (sometimes minutes-long)
    transcript in MENCIONES_COMERCIALES.TRANSCRIPCION."""
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
        detected_marca = mention.get("marca")
        detected_anunciante = mention.get("anunciante")
        num_marca, marca_score = match_marca(detected_marca)
        num_anunc, anunciante_score = match_anunciante(detected_anunciante)

        mentions.append(
            {
                "marca": detected_marca,
                "anunciante": detected_anunciante,
                "num_marca": num_marca,
                "marca_match_score": marca_score,
                "num_anunc": num_anunc,
                "anunciante_match_score": anunciante_score,
                "start": segments[start_idx]["start"],
                "end": segments[end_idx]["end"],
                "mention_transcript": " ".join(
                    segments[i]["text"] for i in range(start_idx, end_idx + 1)
                ),
            }
        )

    return mentions
