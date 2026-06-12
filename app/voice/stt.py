import time
import logging
import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
_model: WhisperModel | None = None

def load_stt_model() -> WhisperModel:
    """Load and warm up Whisper. Call once from lifespan."""
    global _model
    logger.info("Loading STT model (Faster-Whisper small.en, int8)...")
    logger.info("  Downloading model (may take 1-2 min on first run)...")
    t0 = time.time()

    try:
        _model = WhisperModel(
            "small.en",
            device="cpu",
            compute_type="int8",   # int8 is ~2x faster than float32 on CPU, minimal accuracy loss
        )
        elapsed = time.time() - t0
        logger.info(f"  ✓ Model loaded ({elapsed:.1f}s)")
    except Exception as e:
        logger.exception(f"  ✗ Model loading failed: {e}")
        raise

    logger.info("  Pre-warming model (transcribing silence)...")
    t_warm = time.time()
    try:
        # Pre-warm: transcribe 0.5s of silence to trigger JIT compilation
        dummy = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)
        list(_model.transcribe(dummy, language="en")[0])  # consume generator
        elapsed_warm = time.time() - t_warm
        logger.info(f"  ✓ Pre-warm complete ({elapsed_warm:.1f}s)")
    except Exception as e:
        logger.exception(f"  ✗ Pre-warm failed: {e}")
        raise

    total_elapsed = time.time() - t0
    logger.info(f"✓ STT model ready ({total_elapsed:.1f}s total)")
    return _model

def transcribe(pcm_bytes: bytes) -> str:
    """
    Synchronous transcription of raw 16kHz Int16 PCM bytes → text.
    Called via asyncio.to_thread() from the WebSocket handler.
    """
    if _model is None:
        raise RuntimeError("STT model not loaded — call load_stt_model() first")

    import time as _time
    t0 = _time.time()

    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    audio_float32 = audio_int16.astype(np.float32) / 32768.0

    segments, info = _model.transcribe(
        audio_float32,
        language="en",
        beam_size=1,
        vad_filter=False,
        word_timestamps=False,
    )

    text = " ".join(s.text.strip() for s in segments).strip()
    elapsed = _time.time() - t0
    logger.info(f"STT: ({elapsed:.2f}s) → '{text[:80]}'")
    return text