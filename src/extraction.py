import json
import os
import re
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI
from rapidfuzz import fuzz
from rapidfuzz import process as fuzzy_process
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
        rows = (
            conn.execute(text("SELECT TIT_SUB3 FROM SUBCAT3 ORDER BY TIT_SUB3"))
            .scalars()
            .all()
        )
    return list(rows)


@lru_cache(maxsize=1)
def get_anunciantes() -> list[dict]:
    """ANUNCIANTES catalog (15k+ rows) -- too large to hand to an LLM as a closed
    list the way get_categorias()/get_marcas() are, so this backs fuzzy matching
    (match_anunciante()) instead. Cached per-process; the catalog changes rarely
    relative to a single run."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text("SELECT NUM_ANUNC, TIT_ANUNC, ABREV_ANUNC FROM ANUNCIANTES")
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


@lru_cache(maxsize=1)
def get_marcas() -> list[dict]:
    """MARCAS catalog -- small enough (581 rows) to fuzzy-match directly, same
    approach as get_anunciantes(). Cached per-process."""
    with engine.connect() as conn:
        rows = (
            conn.execute(text("SELECT NUM_MARCA, TIT_MARCA FROM MARCAS"))
            .mappings()
            .all()
        )
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
    tit_candidates = {
        r["NUM_ANUNC"]: r["TIT_ANUNC"] for r in anunciantes if r["TIT_ANUNC"]
    }
    abrev_candidates = {
        r["NUM_ANUNC"]: r["ABREV_ANUNC"] for r in anunciantes if r["ABREV_ANUNC"]
    }

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


BRAND_MENTION_SYSTEM_PROMPT = """You are helping a media monitoring company scan discarded audio segments from a radio program (song breaks,
operator chatter, long unclassified stretches — NOT confirmed commercials) for **actual embedded advertising**:
real promotional reads ("spots") hiding inside content that was otherwise discarded as not being a commercial,
so a capturista can review whether each one is worth registering. Missing a real spot is worse than
reporting a borderline one: when a block clearly promotes something specific, report it.

You will be given a transcript as a numbered list of timestamped segments, e.g.:
[0] 0.00-2.40: "..."
[1] 2.40-5.10: "..."
The transcript is automatic speech recognition: names can be misspelled or misheard, and there may be noise.
Report names exactly as written in the transcript.

**What counts as a spot.** A spot is a block of speech whose purpose is to promote a specific product, service,
business, venue, event, offer, contest/ticket giveaway or public campaign to the audience — usually with
concrete details (what, when, where, price or prize, how to participate or contact) and/or a call to action
("ven", "visita", "llama", "disfruta", "te esperamos", "participa", "para obtener tu acceso"). It does NOT need to
be long: a 15–20 second read is a full spot. **The test is promoting vs. informing**: is someone urging the
audience to attend, buy, visit, call, win or take part in something (or presenting an offer for it), as
opposed to reporting facts about what happened or will happen? A news item saying a concert was cancelled
informs; "te esperamos el sábado, gana tus boletos" promotes. A useful cue: promotion speaks *to* the
audience (tú/usted, "ven", "visita", "te invitamos"), while news narrates facts in the third person
("canceló su show", "miles de fanáticos perdieron su dinero"). Typical shapes, all of which must be reported:
- A locutor reading an ad over or between songs.
- A pre-recorded ad that was cut out of the stream, including ones that start or end mid-sentence.
- **Events, concerts, festivals, contests and ticket giveaways promoted on the air, including by the station
  itself.** "La Lupe te invita al Cumbia Fest", "La Lupe presenta … en vivo con Los Yonis … para obtener tu
  acceso", "gana tus boletos en la Zona Lupe" are spots: they pitch a specific named event or prize with
  dates, artists, and how to take part. The event, product or business is the "marca"; the station, organizer
  or sponsor is the "anunciante".
- **Live remote broadcasts / sponsored live reads ("control remoto")**: hosts broadcasting live from a store,
  venue or event who talk up the place, its address, its offers and promotions, prizes, or a brand's product
  (e.g. hosts at a Six store saying the Tecate is ice cold, there are surprises and promotions, come and stock
  up). The tone is informal and chatty, with jokes and banter; that does not disqualify it. If the hosts are
  encouraging listeners to come buy or enjoy a specific brand, store or promotion, report that stretch as a
  spot. Jokes and mini-skits about enjoying the product or visiting the store ("llegas con tu six, con tu
  cervecita", "mira lo que te tengo en el refri") are part of that promotion when the remote is for that
  brand or store. Banter that never mentions or pushes the brand, store or promotion (small talk, sports,
  greetings) is not.
- **Interview-style sponsored segments**: hosts talking with "experts" who pitch their service and repeat a
  call to action — one spot covering the whole segment.
- **Government / public-service announcements** that invite the audience to a named event or campaign with a
  date, place or call to action (e.g. an invitation to a civic celebration, a "hecho en Nuevo León" market,
  a vaccination campaign), the same as any other spot.
- **An institution's closing tag or public-service message** (government agency, consumer protection, health
  campaign: its name, slogan, website, phone or "how to file a complaint / get help") is a public-service spot.
  When it closes an editorial or program segment (a recipe, a talk), report only that tag as the spot — not
  the editorial content before it. The tag starts where the institution itself starts speaking (its name,
  "para acceder a todos los contenidos…", its website/social networks), after the host has said goodbye
  ("gracias por acompañarnos, hasta luego"); the host's own sign-off and invitation to follow the show's
  channels are before the tag and are not part of it. The tag is ONE entry, even when it mentions several
  things (the program, a website, social networks, a complaints line).
- **One ad = one entry.** Do not split a single ad into several entries by its parts (the artists, the prize,
  the contact details, the slogan) — report the whole block once. A closing institutional tag is one entry
  from its first line to its last.
- A single segment can contain **several different spots back to back** (e.g. a concert promo followed by a
  mall's ad). Report each distinct spot separately; do not stop after the first one. If the same ad is aired
  twice in one clip, report it once.

**What does NOT count — do not report these:**
- A brand, person, party or program merely named in passing: in song lyrics, in a DJ's banter, in a news item,
  in a debate or opinion discussion, with no pitch, offer, or promotional framing around it. A bare "Nike"
  dropped mid-sentence is not a spot; "Beadaholique.com, para todas tus necesidades de mostacillas" is.
- News, traffic, weather, sports, entertainment and security reports, even if they mention places, companies,
  artists, concerts or events as facts of the news (e.g. a newscast item saying a singer cancelled or
  rescheduled a concert is news, not an ad). When the clip is a newscast (anchor reading headlines, sign-offs
  like "esto fue El Informe"), nothing in the headlines is a spot, no matter which company, artist or event
  they name; the only exception is a clearly separate promotional tag or sponsor read inside the newscast. A
  newscaster reporting that an event will take place is not a spot; a pre-recorded invitation to it is.
- Song titles, artist/band names, album names and lyrics, and a DJ announcing or taking votes on songs.
  (An artist named inside a promo for a concert or event IS part of that event's spot.)
- Program credits and content identification ("los dejamos con Noticias Caracol", a show's own name or
  intro, a recipe/lifestyle segment's own title).
- Editorial or program content itself — a recipe, an interview that is not a sponsored pitch, a talk, a
  lifestyle segment — even when produced by an institution; and a host inviting listeners to follow the
  show's own YouTube or social channels at the end of such content. Only a separate closing institutional
  tag (see above) is a spot.
- Pure station identification and branding: call sign, frequency, slogan, "escucha La Lupe", weather/time
  jingles, presenter names, with nothing specific being promoted. This still applies when the transcription of
  the station ID is garbled (e.g. "Digital noventa y ocho punto"). Promoting a specific station event, contest
  or product to listeners is different — see above.
- A political party, candidate or government program that is only being discussed, as opposed to a paid or
  public-service promotional read.

**First-person language is not a disqualifier.** Advertisers speak as "we" in their own ad copy ("ven a nuestra
fiesta mexicana … en Paseo La Fe", "tenemos todo para la celebración", "nuestras promociones"). Do not drop a
spot just because it says "nuestro/nuestra/nosotros". Decide by what is being promoted: a named business, event,
product, offer or prize pitched to listeners is a spot; generic "listen to us / follow our networks" branding
with nothing specific is not.

**Transcription noise.** Ignore known Whisper hallucination artifacts — "Subtítulos realizados por la
comunidad de Amara.org", "www.alimmenta.com", "gracias por ver", "suscríbete al canal", "Thank you for watching",
strings of "?" or mismatched-language fragments — they were not said in the clip. Do not report them and do
not treat them as a brand, but also do not let them invalidate real, coherent promotional speech elsewhere in
the same clip: judge each stretch on its own. A short, isolated proper noun sitting inside nonsense is
probably hallucinated; a coherent pitch is real.

For each spot, report (every field below is REQUIRED — never null, never empty):
- "titulo": a short descriptive title of what is being promoted (e.g. "Fiesta mexicana en Paseo La Fe",
  "Promoción de Tecate Light con unidad móvil").
- "marca": the brand, product, event or venue being promoted, as said (e.g. "Paseo La Fe", "Cumbia Fest 2026",
  "Tecate"). If none is named, use a short descriptive label of the product/service.
- "anunciante": the business or organization whose product, venue or event is being promoted, as said — the
  store, the mall or venue hosting the event (e.g. "Paseo La Fe" for a fiesta at Paseo La Fe), the brand, the
  government body. It is NOT the station that merely airs the ad, even if the spot is followed or preceded by
  the station's ID or slogan. Use the station as "anunciante" only when the station itself organizes what is
  promoted (its own concert, festival, contest or ticket giveaway). If the business is never named, use a short
  descriptive label of the kind of advertiser. Do not invent a company name that was not said.
- "start_segment" / "end_segment": the indices of the first and last segment the spot spans — the **whole
  promotional block**, from where the pitch starts through the final call to action or contact details, not
  just the closing details and not the surrounding song or chatter.

**A phone number, WhatsApp line, address, website, social handle or promo code is a contact channel, not a
brand or advertiser.** Never use one as "marca", "anunciante" or "titulo".

If the clip is only music, news, traffic, silence, or conversation with no promotional block, return an empty
list. Do not invent spots.

Write all output text in Spanish (brand/product names stay as mentioned in the transcript).

Respond with JSON only, matching this shape:
{"mentions": [{"titulo": "...", "marca": "...", "anunciante": "...", "start_segment": 0, "end_segment": 0}]}
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
        f'[{i}] {s["start"]:.2f}-{s["end"]:.2f}: "{s["text"]}"'
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
        titulo = (mention.get("titulo") or "").strip()
        detected_marca = (mention.get("marca") or "").strip() or titulo
        detected_anunciante = (mention.get("anunciante") or "").strip() or detected_marca
        titulo = titulo or detected_marca
        num_marca, marca_score = match_marca(detected_marca)
        num_anunc, anunciante_score = match_anunciante(detected_anunciante)

        mentions.append(
            {
                "titulo": titulo,
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
