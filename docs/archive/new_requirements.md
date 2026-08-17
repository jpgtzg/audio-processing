> **Archived.** Mid-project requirement update from the client — kept for history. Superseded by `docs/handoff.md` and `docs/progress.md`, which reflect what's actually confirmed and built since (e.g. Tool 1's write target is now resolved, Tool 2's discard codes are confirmed as locutor/noticiero/cancion rather than open-ended "songs or other reasons").

## Tool1

- The .wav files are already available and croppe in the database
- Transcribe the audio clip using Whisper
- Extract keywords and generate a name/label for the clip
- Spots that are registered more than once should be stored in ALTAS_SARA_FP table with the status Pendiente de Validacion
  so a worker could validate the spot as new. The worker should see the title, transcription and other useful data

## Tool 2

- Will use descarted audio clips (due to songs or other reasons) or too-long clips
- Transcribe the audio clip using Whisper
- Extract keyords and generate a name/label for the clip
- Extract time at which the brand was started to be mentioned and the time at which it was finished to be mentioned
- Will be stored in a table with the status Pendiente de Validacion so a worker could validate the spot as new. The worker should see the title, transcription and other useful data
