import os

from src.audio import transcribe_timestamped_segments
from src.extraction import extract_brand_mentions
from src.tool2.crop import crop_segment
from src.tool2.queries import get_motivo_descarte_labels


def process(segment: dict) -> list[dict]:
    """Transcribes a single discarded/oversized segment (one row from
    queries.fetch_discarded_segments()) and returns one row per detected
    brand mention (a clip can contain zero, one, or several), each carrying
    the source id_segmento/id_testigo/id_estatus_segmento so it can be traced
    back and saved via queries.save_mentions()."""
    clip_path = crop_segment(
        segment["RUTA"], segment["INICIO"], segment["DURACION"], segment["CANAL"]
    )

    try:
        segments = transcribe_timestamped_segments(clip_path)
        full_transcript = " ".join(s["text"] for s in segments)
        mentions = extract_brand_mentions(segments)
    finally:
        os.remove(clip_path)

    return [
        {
            "id_segmento": segment["ID_SEGMENTO"],
            "id_testigo": segment["ID_TESTIGO"],
            "id_estatus_segmento": segment["ID_ESTATUS_SEGMENTO"],
            "motivo_descarte": get_motivo_descarte_labels().get(segment["ID_ESTATUS_SEGMENTO"]),
            "full_transcript": full_transcript,
            **mention,
        }
        for mention in mentions
    ]
