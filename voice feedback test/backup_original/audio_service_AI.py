import os
import time
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from groq import Groq


try:
    sd._terminate()
    sd._initialize()
except Exception:
    pass


SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_DURATION = 0.1

SILENCE_DURATION = 1.2
MAX_RECORDING = 20
START_TIMEOUT = 15
CALIBRATION_DURATION = 1.0

MIN_THRESHOLD = 0.0015
NOISE_MULTIPLIER = 2.0

CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION)
SILENCE_LIMIT = int(SILENCE_DURATION / CHUNK_DURATION)
MAX_CHUNKS = int(MAX_RECORDING / CHUNK_DURATION)
WAIT_CHUNKS = int(START_TIMEOUT / CHUNK_DURATION)
CALIBRATION_CHUNKS = int(CALIBRATION_DURATION / CHUNK_DURATION)

AUDIO_FILE = Path(__file__).resolve().parent / "smart_record.wav"


def get_volume(audio):
    if len(audio) == 0:
        return 0.0

    return float(np.sqrt(np.mean(np.square(audio))))


def record_audio(status_callback=None):

    def report(message):
        if status_callback:
            status_callback(message)

    chunks = []
    pre_roll = deque(maxlen=5)

    started = False
    silence_chunks = 0
    speech_chunks = 0

    try:
        sd.stop()
    except Exception:
        pass

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=CHUNK_SIZE
    ) as stream:

        noise_levels = []

        report("Calibrating microphone…")

        for _ in range(CALIBRATION_CHUNKS):
            audio, overflow = stream.read(CHUNK_SIZE)
            audio = audio.copy().reshape(-1)
            noise_levels.append(get_volume(audio))

        noise_level = (
            float(np.median(noise_levels))
            if noise_levels else MIN_THRESHOLD
        )

        threshold = max(
            MIN_THRESHOLD,
            noise_level * NOISE_MULTIPLIER
        )

        print(
            f"DEBUG noise_level={noise_level:.5f}, "
            f"threshold={threshold:.5f}"
        )

        report("Listening… Speak now")

        for i in range(WAIT_CHUNKS + MAX_CHUNKS):

            audio, overflow = stream.read(CHUNK_SIZE)
            audio = audio.copy().reshape(-1)

            volume = get_volume(audio)

            if not started:

                pre_roll.append(audio)

                if volume >= threshold:
                    started = True
                    chunks.extend(list(pre_roll))
                    speech_chunks = 1
                    report("Recording your voice…")

                elif i + 1 >= WAIT_CHUNKS:
                    raise ValueError(
                        "No clear speech detected. "
                        "Check your microphone and try again."
                    )

                continue

            chunks.append(audio)

            if volume >= threshold:
                speech_chunks += 1
                silence_chunks = 0
            else:
                silence_chunks += 1

            if (
                silence_chunks >= SILENCE_LIMIT
                and speech_chunks >= 3
            ):
                break

            if len(chunks) >= MAX_CHUNKS:
                break

    if not started or not chunks:
        raise ValueError("No audio was recorded.")

    recording = np.concatenate(chunks)

    sf.write(
        str(AUDIO_FILE),
        recording,
        SAMPLE_RATE
    )

    return str(AUDIO_FILE)


def transcribe_audio(audio_file, status_callback=None):

    api_key = os.environ.get("GROQ_API_KEY")

    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is missing. "
            "Set your Groq API key in the terminal."
        )

    if status_callback:
        status_callback("Sending audio to Groq…")

    start_time = time.perf_counter()

    client = Groq(api_key=api_key)

    with open(audio_file, "rb") as audio:
        result = client.audio.transcriptions.create(
            file=(Path(audio_file).name, audio.read()),
            model="whisper-large-v3-turbo",
            response_format="verbose_json",
            temperature=0.0
        )

    return {
        "text": result.text.strip(),
        "language": getattr(result, "language", "unknown"),
        "load_time": 0,
        "transcribe_time": (
            time.perf_counter() - start_time
        )
    }


def listen_and_transcribe(status_callback=None):

    print("Step 1: Starting microphone recording...")

    try:
        audio_file = record_audio(status_callback)
        print("Step 2: Recording completed:", audio_file)

    except Exception as error:
        print("RECORDING ERROR:", repr(error))
        raise

    try:
        print("Step 3: Starting transcription...")

        result = transcribe_audio(
            audio_file,
            status_callback
        )

        print(
            "Step 4: Transcription completed:",
            result["text"]
        )

        return result["text"]

    except Exception as error:
        print("TRANSCRIPTION ERROR:", repr(error))
        raise