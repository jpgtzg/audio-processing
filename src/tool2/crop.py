import tempfile

from pydub import AudioSegment


def crop_segment(testigo_path: str, inicio: float, duracion: float, canal: int) -> str:
    """Crops [inicio, inicio + duracion] out of a testigo recording and exports
    it to a temp wav file for transcription. INICIO/DURACION are in seconds
    (distinct from ALTAS_SARA_FP.INICIO, which is milliseconds).

    Each backup file multiplexes two unrelated station emissions onto stereo
    left/right; CANAL (1=left, 2=right) says which one this row is. Isolating
    that single channel (rather than downmixing both to mono) is required --
    feeding Whisper both channels blended together produces garbled, looping
    transcripts."""
    audio = AudioSegment.from_file(testigo_path)
    if audio.channels >= 2:
        if canal not in (1, 2):
            raise ValueError(f"CANAL must be 1 or 2 to pick a channel, got {canal!r}")
        audio = audio.split_to_mono()[canal - 1]

    start_ms = int(inicio * 1000)
    end_ms = start_ms + int(duracion * 1000)

    tmp_path = tempfile.mktemp(suffix=".wav")
    audio[start_ms:end_ms].export(tmp_path, format="wav")
    return tmp_path
