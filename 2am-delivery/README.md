# THE 2AM DELIVERY

Original second-person "what would you do?" short (84 s, 1080x1920, 30 fps). Flat 2D, dark UI style:
HUD (time / cash / risk), red thought labels, app-style cards, captions with red/blue key words, ending on a choice.
Main character: the house character (white stick figure, red hoodie, black joggers). Voice: house male voice
(Kokoro `am_puck`, ~180 wpm, see `../voice/VOICE.md`).

Build (`SCR` = scratch dir with the Kokoro model files, python venv with kokoro-onnx, Pillow, numpy, soundfile):

    python tts.py        # voiceover + timeline.json (caption timings)
    python audio.py      # score, sfx, mix -> $SCR/2am_mix.wav
    python render.py --still 12.5 frame.png
    python render.py 0 2519 video.mp4    # then mux with the mix (see the render script used in the session)
