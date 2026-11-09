# Makes Professor Byte's voice clips for an episode.
# Setup: pip install kokoro-onnx soundfile; download kokoro-v1.0.int8.onnx and voices-v1.0.bin from
# https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0 into $KOKORO_DIR (needs ffmpeg).
# Run: python make_voice.py episode.html out_dir af_heart  -> out_dir/audio.js, paste it into the episode as its own <script>.
import re, sys, json, subprocess, os, base64
import soundfile as sf
from kokoro_onnx import Kokoro
src, outdir, voice = sys.argv[1], sys.argv[2], sys.argv[3]
html = open(src).read()
blocks = re.findall(r'lines: \[(.*?)\]\s*\}', html, re.S)
scenes = [re.findall(r'"((?:[^"\\]|\\.)*)"', b) for b in blocks]
KEEP = {"IP","HTTP","HTTPS","SSH","DNS","TCP","UDP","SOC","OSI","MAC","LAN","ARP","TLS"}
def speak(t):
    t = re.sub(r'\*(.+?)\*', '', t)
    t = re.sub(r'[\U0001F300-\U0001FAFF☀-➿️]', '', t)
    t = t.replace('…', '...').replace('SYN-ACK', 'sin-ack').replace('IPv4', 'I P v four')
    t = re.sub(r'\bSYN\b', 'sin', t); t = re.sub(r'\bACK\b', 'ack', t)
    t = re.sub(r'\b[A-Z]{2,}\b', lambda m: m.group(0) if m.group(0) in KEEP else m.group(0).lower(), t)
    t = t.replace('netflix dot com', 'netflix dot com')
    return t.strip()
k = Kokoro(f"{os.environ.get("KOKORO_DIR", "model")}/kokoro-v1.0.int8.onnx", f"{os.environ.get("KOKORO_DIR", "model")}/voices-v1.0.bin")
os.makedirs(outdir, exist_ok=True)
out = []
for si, lines in enumerate(scenes):
    row = []
    for li, line in enumerate(lines):
        text = speak(line)
        samples, sr = k.create(text, voice=voice, speed=1.05, lang="en-us")
        wav = f"{outdir}/s{si}l{li}.wav"; mp3 = wav[:-3] + "mp3"
        sf.write(wav, samples, sr)
        subprocess.run(["ffmpeg","-y","-loglevel","error","-i",wav,"-ac","1","-ar","24000","-b:a","48k",mp3], check=True)
        row.append("data:audio/mpeg;base64," + base64.b64encode(open(mp3,"rb").read()).decode())
        print(si, li, round(len(samples)/sr,1), text, flush=True)
    out.append(row)
open(f"{outdir}/audio.js","w").write("window.AUDIO = " + json.dumps(out) + ";\n")
