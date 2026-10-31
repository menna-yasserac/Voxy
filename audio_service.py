
import time
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel


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

_model = None


def get_volume(audio):
    return float(np.sqrt(np.mean(np.square(audio))))


def get_model():
    """Load Faster-Whisper once and reuse it."""
    global _model

    if _model is None:
        _model = WhisperModel(
            "large-v3-turbo",
            device="cpu",
            compute_type="int8"
        )

    return _model


def record_audio(status_callback=None):
    """Record until speech ends or the recording limit is reached."""

    def report(message):
        if status_callback:
            status_callback(message)

    chunks = []
    pre_roll = deque(maxlen=5)

    started = False
    silence_chunks = 0
    speech_chunks = 0

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=CHUNK_SIZE
    ) as stream:

        # Calibrate the microphone's background noise.
        noise_levels = []

        report("Calibrating microphone…")

        for _ in range(CALIBRATION_CHUNKS):
            audio, _ = stream.read(CHUNK_SIZE)
            audio = audio.copy().reshape(-1)
            noise_levels.append(get_volume(audio))

        noise_level = float(np.median(noise_levels))

        threshold = max(
            MIN_THRESHOLD,
            noise_level * NOISE_MULTIPLIER
        )

        print(f"DEBUG noise_level={noise_level:.5f}, threshold={threshold:.5f}")

        report("Listening… Speak now")

        for i in range(WAIT_CHUNKS + MAX_CHUNKS):
            audio, _ = stream.read(CHUNK_SIZE)
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
    sf.write(str(AUDIO_FILE), recording, SAMPLE_RATE)

    return str(AUDIO_FILE)


def transcribe_audio(audio_file, status_callback=None):
    """Convert recorded audio into text."""

    def report(message):
        if status_callback:
            status_callback(message)

    load_start = time.perf_counter()
    model = get_model()
    load_time = time.perf_counter() - load_start

    report("Recognizing speech…")

    transcribe_start = time.perf_counter()

    segments, info = model.transcribe(
    audio_file,
    language=None,
    beam_size=5
)
    # Faster-Whisper completes inference as segments are consumed.
    recognized_text = "".join(
        segment.text for segment in segments
    ).strip()

    transcribe_time = time.perf_counter() - transcribe_start

    return {
        "text": recognized_text,
        "language": info.language,
        "load_time": load_time,
        "transcribe_time": transcribe_time
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
        result = transcribe_audio(audio_file, status_callback)
        print("Step 4: Transcription completed:", result["text"])
        return result
    except Exception as error:
        print("TRANSCRIPTION ERROR:", repr(error))
        raise
