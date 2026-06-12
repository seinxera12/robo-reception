import asyncio
import os
import warnings

# Must be set before kokoro/huggingface imports
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

# Kokoro prints this directly via warnings.warn before we can intercept it
warnings.filterwarnings("ignore", message=r".*Defaulting repo_id.*")

import re
import time
import logging
import numpy as np
from typing import AsyncIterator

logger = logging.getLogger(__name__)

_pipeline = None
SAMPLE_RATE = 24000   # Kokoro outputs at 24kHz
VOICE = "af_heart"    # default Kokoro voice — warm, neutral, reception-appropriate


def load_tts_model():
    """Load and warm up Kokoro. Call once from lifespan."""
    global _pipeline
    
    logger.info("Loading TTS model (Kokoro American English)...")
    logger.info("  Importing KPipeline...")
    
    from kokoro import KPipeline
    logger.info("  ✓ KPipeline imported")
    
    logger.info("  Creating pipeline (may take 30-60s on first run)...")
    t0 = time.time()

    try:
        # Kokoro emits a repo_id warning via print() to stderr — redirect to suppress it
        import io
        _stderr_capture = io.StringIO()
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=r".*Defaulting repo_id.*")
            warnings.filterwarnings("ignore", message=r".*dropout option.*")
            warnings.filterwarnings("ignore", message=r".*weight_norm.*")
            import sys as _sys
            _real_stderr, _sys.stderr = _sys.stderr, _stderr_capture
            try:
                _pipeline = KPipeline(lang_code="a")
            finally:
                _sys.stderr = _real_stderr
        elapsed = time.time() - t0
        logger.info(f"  ✓ Pipeline created ({elapsed:.1f}s)")
    except Exception as e:
        logger.exception(f"  ✗ Pipeline creation failed: {e}")
        raise

    logger.info("  Pre-warming pipeline (synthesizing test phrase)...")
    t_warm = time.time()
    try:
        dummy = list(_pipeline("Welcome.", voice=VOICE))
        elapsed_warm = time.time() - t_warm
        logger.info(f"  ✓ Pre-warm complete ({elapsed_warm:.1f}s)")
    except Exception as e:
        logger.exception(f"  ✗ Pre-warm failed: {e}")
        raise

    total_elapsed = time.time() - t0
    logger.info(f"✓ TTS model ready ({total_elapsed:.1f}s total)")


def _split_sentences(text: str) -> list[str]:
    """
    Split text into sentences for streaming.
    Minimum 4 words per sentence to avoid single-word chunks.
    """
    raw = re.split(r'(?<=[.?!])\s+', text.strip())
    sentences = []
    pending = ""

    for sentence in raw:
        combined = (pending + " " + sentence).strip() if pending else sentence
        word_count = len(combined.split())

        if word_count >= 4:
            sentences.append(combined)
            pending = ""
        else:
            pending = combined

    if pending:
        sentences.append(pending)

    return sentences if sentences else [text]


def synthesise(text: str) -> list[bytes]:
    """
    Synchronous version — synthesise full response, return list of Int16 PCM chunks.
    Called via asyncio.to_thread() from the WebSocket handler.
    """
    if _pipeline is None:
        raise RuntimeError("TTS model not loaded — call load_tts_model() first")

    sentences = _split_sentences(text)
    logger.info(f"TTS: {len(sentences)} sentence(s), {len(text)} chars")

    result = []
    for i, sentence in enumerate(sentences, 1):
        import time as _time
        t0 = _time.time()

        audio_chunks = list(_pipeline(sentence, voice=VOICE))
        if not audio_chunks:
            continue

        audio_arrays = [c[2] for c in audio_chunks if c[2] is not None]
        if not audio_arrays:
            continue

        audio = np.concatenate(audio_arrays)
        pcm_bytes = (audio * 32767).astype(np.int16).tobytes()
        result.append(pcm_bytes)

        logger.debug(f"TTS: sentence {i}/{len(sentences)} ({_time.time()-t0:.2f}s) → {len(pcm_bytes)} bytes")

    return result


async def synthesise_stream(text: str) -> AsyncIterator[bytes]:
    """
    Async generator wrapper — yields chunks one at a time.
    Note: each yield still blocks briefly; prefer synthesise() + to_thread for WebSocket use.
    """
    chunks = await asyncio.get_event_loop().run_in_executor(None, synthesise, text)
    for chunk in chunks:
        yield chunk