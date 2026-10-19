import numpy as np
import openwakeword
from openwakeword.model import Model

class WakeWordDetector:
    def __init__(self, model_name: str = "hey_jarvis", threshold: float = 0.5):
        self.model_name = model_name
        self.threshold = threshold
        # Initialize model
        self.model = Model(wakeword_models=[model_name])

    def predict(self, audio_chunk_16khz: np.ndarray) -> bool:
        """Takes 16kHz audio chunk (int16 or float32) and checks for wake word."""
        if audio_chunk_16khz.dtype == np.float32:
            audio_int16 = (audio_chunk_16khz * 32767).astype(np.int16)
        else:
            audio_int16 = audio_chunk_16khz

        prediction = self.model.predict(audio_int16)
        for name, score in self.model.prediction_buffer.items():
            if len(score) > 0 and score[-1] >= self.threshold:
                self.model.reset()
                return True
        return False

    def reset(self):
        self.model.reset()
