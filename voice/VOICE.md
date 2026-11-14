# House narrator voice (approved)

Use this voice for all future shorts unless told otherwise. Approved on the final cut of
"35 MILLION" (`35-million/out/35_million_720p.mp4`). Listen: `narrator_reference.m4a`.

**Do not** pitch-shift it, deepen it or "add emotion" with audio effects. That changed the voice and was rejected.
The emotion comes from pace, breaths and punctuation only.

## Engine
- Kokoro v1.0 (local neural TTS, `kokoro-onnx` 0.6.x), model files `kokoro-v1.0.onnx` + `voices-v1.0.bin`
  from the kokoro-onnx GitHub release `model-files-v1.0`.
- Narrator voice: **`am_puck`** (US male, sounds about 25).
- Second male character (e.g. the agent): `am_onyx` at speed 0.765.

## Delivery: hurried, like he's living it
- Pace: **~180 words per minute** including pauses and breaths. Calibrate the Kokoro `speed` per script
  (see `35-million/tts2.py`, `TARGET_WPM = 180`); it lands around 0.8–0.9.
- `kk.create(..., sentence_pause=0.14, clause_pause=0.04)`.
- Pauses only at "…": 0.28 s; 0.42 s when it leads into a big reveal.
- A quick, quiet breath (0.24 s, band-passed noise, peak 0.05) before the urgent or panicked lines.
- Per-line speed nudges only: rules ×0.96, the run ×1.04, the dark reveals ×0.92–0.93.
- Key-word phrase (the lime-highlighted word) +2 dB, volume only.
- Exclamation marks on the adrenaline lines ("Thirty-five million dollars!", "So you run!").
- Post: `aresample=44100,aecho=0.8:0.5:40|80:0.06|0.03` (a touch of room, nothing else).
- Captions: split each line into (spoken words, caption chunk) pairs; place chunk boundaries by phoneme share,
  snapped to real silences in the audio (`35-million/tts2.py`).
