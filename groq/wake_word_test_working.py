import sounddevice as sd
import numpy as np
from openwakeword.model import Model

# Configuration
MODEL_PATH = "models/voxy_single.onnx"
SAMPLE_RATE = 16000
CHUNK_SIZE = 1280
THRESHOLD = 0.5

# Load custom wake-word model
model = Model(
    wakeword_models=[MODEL_PATH],
    inference_framework="onnx"
)

print("\nVoxy wake-word detector is ready.")
print("Say 'Voxy' to test detection.")
print("Press Ctrl+C to stop.\n")

try:
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK_SIZE
    ) as stream:

        while True:
            audio, overflowed = stream.read(CHUNK_SIZE)

            audio = np.squeeze(audio)

            prediction = model.predict(audio)

            for wake_word, score in prediction.items():
                if score > THRESHOLD:
                    print(f"Voxy detected! Confidence: {score:.3f}")
                    model.reset()

except KeyboardInterrupt:
    print("\nTest stopped.")
