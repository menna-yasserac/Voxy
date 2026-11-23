import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
from openwakeword.model import Model


class WakeWordService:

    SAMPLE_RATE = 16000
    CHUNK_SIZE = 1280
    THRESHOLD = 0.5

    def __init__(self, on_wake):
        self.on_wake = on_wake

        self.model_path = (
            Path(__file__).resolve().parent
            / "models"
            / "voxy_single.onnx"
        )

        self.model = None
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return

            self.stop_event.clear()

            self.thread = threading.Thread(
                target=self._listen,
                daemon=True
            )
            self.thread.start()

    def stop(self):
        self.stop_event.set()

        thread = self.thread

        if thread and thread.is_alive():
            if thread is not threading.current_thread():
                thread.join(timeout=2)

    def _listen(self):

        try:
            if self.model is None:
                self.model = Model(
                    wakeword_models=[str(self.model_path)],
                    inference_framework="onnx"
                )

            print("[WakeWord] Listening for Voxy...", flush=True)

            detected = False

            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=self.CHUNK_SIZE
            ) as stream:

                while not self.stop_event.is_set():

                    audio, overflowed = stream.read(self.CHUNK_SIZE)

                    if self.stop_event.is_set():
                        break

                    audio = np.squeeze(audio)

                    prediction = self.model.predict(audio)

                    score = max(prediction.values(), default=0)

                    if score >= self.THRESHOLD:
                        print(
                            f"[WakeWord] Voxy detected! Score: {score:.3f}",
                            flush=True
                        )

                        self.model.reset()
                        detected = True
                        break

            # The microphone stream is closed before this callback.
            if detected and not self.stop_event.is_set():
                self.on_wake()

        except Exception:
            import traceback
            print("[WakeWord] ERROR:", flush=True)
            traceback.print_exc()
