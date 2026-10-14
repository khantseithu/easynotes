# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#   "mlx-audio==0.5.9",
#   "misaki[en]==0.9.4",
#   "soundfile==0.14.0",
#   "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
# ]
# ///
import argparse
import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import numpy as np
import soundfile as sf
from mlx_audio.tts.utils import load_model

ap = argparse.ArgumentParser()
ap.add_argument("text_file")
ap.add_argument("out_wav")
ap.add_argument("--voice", default="af_heart")
ap.add_argument("--model", default="mlx-community/Kokoro-82M-bf16")
args = ap.parse_args()

paragraphs = [p.strip() for p in open(args.text_file).read().split("\n\n") if p.strip()]
model = load_model(args.model)
pause = np.zeros(int(24000 * 0.35), dtype=np.float32)
frames = 0
with sf.SoundFile(args.out_wav, "w", samplerate=24000, channels=1) as out:
    for i, para in enumerate(paragraphs, 1):
        for r in model.generate(text=para, voice=args.voice, speed=1.0, lang_code=args.voice[0]):
            audio = np.array(r.audio, dtype=np.float32).reshape(-1)
            out.write(audio)
            frames += audio.size
        out.write(pause)
        frames += pause.size
        print(f"progress {i / len(paragraphs):.3f}", flush=True)
print(f"secs {frames / 24000:.1f}", flush=True)
