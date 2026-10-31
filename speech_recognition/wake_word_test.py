import time
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
CHUNK_DURATION = 0.25

# Silence detection settings
SILENCE_DURATION = 1.2
MAX_COMMAND_DURATION = 15
MIN_COMMAND_DURATION = 0.5

# Microphone sensitivity
SILENCE_THRESHOLD = 0.015

print("Loading Faster-Whisper Large-v3-Turbo...")

model = WhisperModel(
    "large-v3-turbo",
    device="cpu",
    compute_type="int8"
)

print("Voxy is ready!")


def record_chunk():
    """Record a short microphone chunk."""
    audio = sd.rec(
        int(CHUNK_DURATION * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32"
    )
    sd.wait()
    return np.squeeze(audio)


def transcribe_audio(audio):
    """Transcribe speech and automatically detect its language."""
    segments, info = model.transcribe(
        audio.astype(np.float32),
        language=None,
        beam_size=5,
        vad_filter=True
    )

    text = "".join(segment.text for segment in segments).strip()

    return text, info.language


def contains_wake_word(text):
    """Check for Voxy's wake word."""
    normalized = text.lower().strip()
    normalized = normalized.replace("-", " ")
    normalized = normalized.replace(",", "")
    normalized = normalized.replace(".", "")

    wake_phrases = [
        "voxy",
        "hey voxy",
        "foxy",
        "hey foxy",
    ]

    return any(phrase in normalized for phrase in wake_phrases)


def listen_for_wake_word():
    """
    Listen continuously in short chunks.
    Every few seconds, use Whisper to check for the wake word.
    """
    print("\nListening for 'Voxy'...")

    audio_buffer = []
    check_interval = 3
    chunks_per_check = int(check_interval / CHUNK_DURATION)

    while True:
        chunk = record_chunk()
        audio_buffer.extend(chunk)

        if len(audio_buffer) >= SAMPLE_RATE * check_interval:
            audio = np.array(audio_buffer, dtype=np.float32)

            text, language = transcribe_audio(audio)

            print(f"Heard: {text}")

            if contains_wake_word(text):
                print("\nVoxy activated!")
                return


def listen_for_command():
    """
    Wait for speech, then stop recording after enough silence.
    """
    print("\nI'm listening. Speak your command now.")

    command_chunks = []
    speech_started = False
    silence_time = 0
    elapsed_time = 0

    while elapsed_time < MAX_COMMAND_DURATION:
        chunk = record_chunk()
        command_chunks.append(chunk)

        elapsed_time += CHUNK_DURATION

        volume = np.sqrt(np.mean(chunk ** 2))

        if volume >= SILENCE_THRESHOLD:
            speech_started = True
            silence_time = 0
        elif speech_started:
            silence_time += CHUNK_DURATION

        # Stop after the user finishes speaking.
        if speech_started and silence_time >= SILENCE_DURATION:
            break

    if not speech_started:
        print("I didn't hear a command.")
        return

    audio = np.concatenate(command_chunks).astype(np.float32)

    if len(audio) < SAMPLE_RATE * MIN_COMMAND_DURATION:
        print("The command was too short. Please try again.")
        return

    print("\nRecognizing your command...")

    text, language = transcribe_audio(audio)

    print("\n========== COMMAND RESULTS ==========")
    print("Command:", text)
    print("Detected language:", language)
    print("=====================================")


try:
    while True:
        input("\nPress ENTER to activate Voxy, or Ctrl+C to quit.")

        listen_for_wake_word()
        listen_for_command()

except KeyboardInterrupt:
    print("\nVoxy stopped. Goodbye!")
