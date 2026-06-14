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
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_MS / 1000)  # 480 samples per 30ms chunk
CHUNK_BYTES = CHUNK_SAMPLES * 2                      # 960 bytes (Int16 = 2 bytes/sample)

# Silero VAD enforces: sr / chunk_samples > 31.25 raises ValueError.
# At 16000Hz: minimum chunk = ceil(16000 / 31.25) = 512 samples = 1024 bytes.
# We accumulate incoming 480-sample chunks and process in 512-sample (1024-byte) windows.
VAD_MIN_SAMPLES = 512
VAD_MIN_BYTES = VAD_MIN_SAMPLES * 2  # 1024 bytes

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
        self._byte_buffer: bytes = b""  # accumulates bytes until MIN_SAMPLES are ready
        _model.reset_states()
        logger.debug("VADProcessor initialized")

    def process_chunk(self, pcm_bytes: bytes) -> tuple[bool, bytes | None]:
        """
        Feed a raw PCM chunk (960 bytes = 480 samples = 30ms at 16kHz).
        Accumulates bytes until at least VAD_MIN_BYTES (1024 = 512 samples) are
        available, then processes in 512-sample windows — the minimum Silero accepts.

        Returns:
            (is_speaking, completed_utterance_bytes | None)
        """
        self._byte_buffer += pcm_bytes

        if len(self._byte_buffer) < VAD_MIN_BYTES:
            return self._is_speaking, None

        # Process all complete VAD_MIN_BYTES windows; leave remainder for next call
        last_result = (self._is_speaking, None)
        while len(self._byte_buffer) >= VAD_MIN_BYTES:
            chunk = self._byte_buffer[:VAD_MIN_BYTES]
            self._byte_buffer = self._byte_buffer[VAD_MIN_BYTES:]

            last_result = self._process_pcm(chunk)
            if last_result[1] is not None:
                return last_result

        return last_result

    def _process_pcm(self, pcm_bytes: bytes) -> tuple[bool, bytes | None]:
        """Run VAD on a single validated PCM chunk."""
        audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio_float32)

        confidence = _model(tensor, SAMPLE_RATE).item()
        is_speech = confidence > 0.5

        # Log confidence every ~1s so we can diagnose VAD in real time
        if not hasattr(self, '_vad_call_count'):
            self._vad_call_count = 0
            self._max_confidence = 0.0
        self._vad_call_count += 1
        if confidence > self._max_confidence:
            self._max_confidence = confidence
        if self._vad_call_count % 33 == 0:  # ~every 1 second (33 × 30ms chunks)
            logger.info(
                f"VAD: call#{self._vad_call_count} "
                f"conf={confidence:.3f} max={self._max_confidence:.3f} "
                f"speaking={self._is_speaking}"
            )
        if is_speech and self._vad_call_count <= 5:
            logger.info(f"VAD: SPEECH DETECTED early — conf={confidence:.3f} on call #{self._vad_call_count}")

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
