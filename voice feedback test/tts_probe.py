#!/usr/bin/env python3
"""
Run this ON YOUR VM (needs internet + `pip install edge-tts` + ffplay/mpv).
Generates every test sentence with each mixed-language strategy, prints the
latency, saves the mp3 files to ./probe_out and (optionally) plays them so you
can judge Egyptian Arabic, English and mixed pronunciation by ear.

    python3 tts_probe.py            # generate + play
    python3 tts_probe.py --no-play  # generate only
"""
import subprocess, sys, time
from pathlib import Path
import voice_feedback as vf

SENTENCES = [
    ("ar",    "تمام، المهمة خلصت بنجاح."),
    ("ar",    "حصلت مشكلة أثناء تنفيذ الأمر."),
    ("ar",    "ثانية واحدة، أنا بجهز طلبك."),
    ("en",    "Your command has been executed successfully."),
    ("en",    "Sorry, I couldn't complete this operation."),
    ("mixed", "تمام، أنا خلصت الـ preprocessing، ودلوقتي هبدأ أشغل الـ execution."),
    ("mixed", "تمام، Your task is completed successfully."),
    ("mixed", "فتحت الـ GUI وشغلت الـ API على port 8080."),
    ("mixed", "الـ threading شغال، وعندي 3 files جاهزين."),
    ("ar",    "افتح فايرفوكس."),
]

out = Path("probe_out"); out.mkdir(exist_ok=True)
play = "--no-play" not in sys.argv

for strategy in ("single", "split"):
    provider = vf.EdgeTTSProvider(mixed_strategy=strategy)
    print(f"\n=== mixed strategy: {strategy} "
          f"(ar={provider.ar_voice}, en={provider.en_voice}) ===")
    for i, (lang, text) in enumerate(SENTENCES):
        if strategy == "split" and lang != "mixed":
            continue                     # identical to 'single' for pure text
        t0 = time.perf_counter()
        try:
            data = provider.synthesize(text, lang, "+0%")
        except Exception as e:
            print(f"  FAIL [{lang}] {text}\n       {type(e).__name__}: {e}")
            continue
        dt = time.perf_counter() - t0
        f = out / f"{strategy}_{i:02d}_{lang}.mp3"
        f.write_bytes(data)
        print(f"  {dt:5.2f}s  {len(data)/1024:5.1f} KB  [{lang}] {text}")
        if play:
            subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel",
                            "quiet", str(f)])
