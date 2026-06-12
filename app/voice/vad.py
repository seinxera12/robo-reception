import logging
import torch
import numpy as np

logger = logging.getLogger(__name__)

# Load once at module level - subsequent imports reuse this
logger.debug("Loading Silero VAD model from torch hub...")
_model, _utils = torch.hub.load(        # ← was _model_ (typo), VADProcessor used _model
    repo_or_dir="snakers4/silero-vad",
    model="silero_vad",
    force_reload=False,
    onnx=False
)
logger.info("✓ Silero VAD model loaded")

_get_speech_ts = _utils[0]

SAMPLE_RATE = 16000
CHUNK_MS = 30
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_MS / 1000)
SILENCE_THRESHOLD_MS = 600
SILENCE_CHUNKS = SILENCE_THRESHOLD_MS // CHUNK_MS


class VADProcessor:
    """
    Stateful per-session VAD processor. One instance per WebSocket connection.
    """

    def __init__(self):
        self._speech_buffer: list[bytes] = []
        self._silence_count: int = 0
        self._is_speaking: bool = False
        _model.reset_states()
        logger.debug("VADProcessor initialized")

    def process_chunk(self, pcm_bytes: bytes) -> tuple[bool, bytes | None]:
        """
        Feed a 30ms PCM chunk.

        Returns:
            (is_speaking, completed_utterance_bytes | None)
        """
        audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio_float32)

        confidence = _model(tensor, SAMPLE_RATE).item()
        is_speech = confidence > 0.5

        if is_speech:
            self._is_speaking = True
            self._silence_count = 0
            self._speech_buffer.append(pcm_bytes)
            return True, None

        elif self._is_speaking:
            self._speech_buffer.append(pcm_bytes)
            self._silence_count += 1

            if self._silence_count >= SILENCE_CHUNKS:
                utterance = b"".join(self._speech_buffer)
                duration_s = len(utterance) / (SAMPLE_RATE * 2)  # 16-bit = 2 bytes/sample
                logger.info(f"VAD: Utterance complete — {len(self._speech_buffer)} chunks, {duration_s:.1f}s")
                self._reset()
                return False, utterance

            return True, None

        return False, None

    def _reset(self):
        self._speech_buffer = []
        self._silence_count = 0
        self._is_speaking = False
        _model.reset_states()
