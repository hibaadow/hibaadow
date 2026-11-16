# The Vice City Diaries — Episode 1 (unofficial fan-made animation)

Real-time 3D crime-drama short, 9:16 (1080×1920), ~90 s. Plain HTML + JavaScript + [Three.js](https://threejs.org) (MIT, vendored in `vendor/three`), no build step.
Not affiliated with or endorsed by Rockstar Games; no game files, logos or ripped assets are used. All models (city, cars,
Lucia and Jason) are original procedural designs built in code.

## Play it
```
cd vice-city-diaries && python3 -m http.server 8765
# open http://localhost:8765  → tap to play · ↺ Replay · ⬇ Export MP4
```
`?q=0.5` lowers the internal render resolution on slow devices.

## What's in it
- `js/main.js` — the whole episode: procedural city (buildings with lit windows, neon signs, palms, traffic, ocean, sky),
  rigged procedural characters (walk / sit / phone / head turns, blinking, brows, lip movement driven by the dialogue audio),
  cars and SUV, phone + bag props, 20+ camera shots (aerial, over-the-shoulder, close-ups, tracking, chase), whip-pan / dip
  transitions, bloom + colour grade + grain, subtitles. One clock (`renderAt(t)`) drives everything.
- `data/timeline.json` — dialogue lines + per-speaker mouth envelopes (from `tools/tts.py`).
- `audio/soundtrack.m4a` — score, ambience, SFX and dialogue (from `tools/audio.py`).

## Export
- **In the browser:** ⬇ Export MP4 records the canvas + soundtrack in real time (MP4 where the browser supports it, WebM otherwise).
- **Frame-exact MP4 (offline):** with the server running, `node tools/render_mp4.cjs <startFrame> <endFrame> part.mp4` renders
  any range at 30 fps in headless Chromium; render ranges in parallel, concat them, then mux the soundtrack WAV/M4A.

## Regenerate voices / sound
`SCR=<workdir> python tools/tts.py` (Kokoro neural TTS: Lucia = af_heart, Jason = am_fenrir, caller = am_onyx + phone EQ),
then `SCR=<workdir> python tools/audio.py`.
