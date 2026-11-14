# The Man by the Lift — 9:16 psychological thriller short (~2:18)

Same look and toolkit as `../35-million` (imports its renderer). Narrator follows `../voice/VOICE.md`
(house delivery), with a female voice because the story is told by a girl.

1. `python tts.py` — Kokoro: her = af_heart (~180 wpm, breaths), him = am_onyx, neighbour = am_puck, reception = af_sarah → `$SCR/vo_lift/`
2. `python audio.py` → `$SCR/soundtrack_lift.wav`
3. `python render.py <start_frame> <end_frame> out.mp4` (or `--still <t> out.png`); shots are timed from the voiceover.
