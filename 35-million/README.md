# 35 Million — 9:16 thriller short

Same pipeline and character as `../last-bus` (it imports that renderer's drawing toolkit).

1. `python tts.py` — Kokoro voices (narrator "Michael", agent "Onyx") → `$SCR/vo35/`
2. `python audio.py` — drone, heartbeat, sirens, SFX + VO → `$SCR/soundtrack35.wav`
3. `python render.py <start_frame> <end_frame> out.mp4` (or `--still <t> out.png`), then mux with the soundtrack.
