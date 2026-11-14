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

---

# Girl narrator + girl character (approved)

Use these whenever the story is about / told by a girl. Approved on the final cut of
"THE MAN BY THE LIFT" (`man-by-the-lift/out/the_man_by_the_lift_720p.mp4`). Listen: `narrator_female_reference.m4a`.

## Voice
- Kokoro v1.0, voice **`af_heart`** (young US woman).
- Exactly the same delivery as the male house voice above: hurried **~180 wpm** including pauses and breaths
  (calibrated; Kokoro speed lands around 1.03), `sentence_pause=0.14`, `clause_pause=0.04`,
  pauses only at "…" (0.28 s, 0.55 s into a reveal), quick quiet breaths before tense lines,
  `aresample=44100,aecho=0.8:0.5:40|80:0.06|0.03`, no pitch effects. Recipe: `man-by-the-lift/tts.py`.
- Story flows: **do not** have her read chapter titles. Chapter names are a small red label over the scene (no pause).
- Other voices used with her: the man = `am_onyx` (speed 0.84, darker room), a young male neighbour = `am_puck`,
  a receptionist = `af_sarah`.

## Character
- The same main character as the other shorts: plain white stick figure, round head, small dot eyes when scared,
  **red hoodie (hood down behind the head, drawstrings, front pocket) + black joggers + white trainers**,
  plus **long dark-brown hair** (`HAIR = (44, 30, 28)`): side panels framing the face and a fringe;
  from behind, a full head of hair falling over the hood. See `girl_character.png`.
- Code: `girl(cv, x, foot_y, s, eyes, look, back=False)` in `man-by-the-lift/render.py`
  (built on `you_stand` / `hoodie_body` from `35-million/render.py`).
