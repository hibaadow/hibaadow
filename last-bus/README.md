# The Last Bus — 9:16 horror short

1080x1920, 30fps, ~90s. Flat 2D vector frames drawn with Pillow; voice by Piper TTS.

Needs `SCR` pointing at a working dir with `venv/` (piper-tts, pillow, numpy), `voices/` (Piper en_GB alan + jenny_dioco), `fonts/` (Anton, VT323).

1. `python tts.py` — voiceover lines from `script.py` → `$SCR/vo/`
2. `python audio.py` — drone, rain, SFX + VO mix → `$SCR/soundtrack.wav`
3. `python render.py <start_frame> <end_frame> out.mp4` (or `--still <t> out.png`), then mux with the soundtrack.
