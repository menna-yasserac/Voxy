import time
import sounddevice as sd
import soundfile as sf
from pathlib import Path
from faster_whisper import WhisperModel

# Audio settings
SAMPLE_RATE = 16000
DURATION = 8

# Save the recording in our testing folder
AUDIO_FILE = Path(__file__).resolve().parent / "test_audio.wav"


def record_audio():
    """Record a short audio sample from the microphone."""

    print("\nRecording will start in 3 seconds.")
    print("Get ready to speak!")

    time.sleep(3)

    print("Recording... Speak now!")

    audio = sd.rec(
        int(DURATION * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32"
    )

    sd.wait()

    sf.write(str(AUDIO_FILE), audio, SAMPLE_RATE)

    print("Recording saved:", AUDIO_FILE)


def transcribe_audio():
    """Load Faster-Whisper Large and transcribe the recording."""

    print("\nLoading Faster-Whisper Large-v3-Turbo...")
    print("The first run may take several minutes to download the model.")

    load_start = time.perf_counter()

    model = WhisperModel(
        "large-v3-turbo",
        device="cpu",
        compute_type="int8"
    )

    load_time = time.perf_counter() - load_start

    print(f"Model loaded in {load_time:.2f} seconds.")

    print("\nTranscribing your recording...")

    start = time.perf_counter()

    segments, info = model.transcribe(
        str(AUDIO_FILE),
        language=None,
        beam_size=5
    )

    text = "".join(segment.text for segment in segments).strip()

    transcription_time = time.perf_counter() - start

    print("\n========== RESULTS ==========")
    print("Transcribed text:", text)
    print("Detected language:", info.language)
    print(f"Language confidence: {info.language_probability:.2f}")
    print(f"Model loading time: {load_time:.2f} seconds")
    print(f"Transcription time: {transcription_time:.2f} seconds")
    print("=============================")


if __name__ == "__main__":
    record_audio()
    transcribe_audio()
