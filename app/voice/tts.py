import asyncio
import io
import os
import sys
import warnings
import re
import time
import logging
import numpy as np
from typing import AsyncIterator

# Kokoro prints this directly via warnings.warn before we can intercept it
warnings.filterwarnings("ignore", message=r".*Defaulting repo_id.*")

logger = logging.getLogger(__name__)

_pipeline = None
SAMPLE_RATE = 24000   # Kokoro outputs at 24kHz
VOICE = "af_heart"    # default Kokoro voice — warm, neutral, reception-appropriate


def load_tts_model():
    """Load and warm up Kokoro. Call once from lifespan."""
    global _pipeline

    logger.info("Loading TTS model (Kokoro American English)...")
    logger.info("  Importing KPipeline...")

    # Kokoro ships its model files locally (installed via pip), so it doesn't
    # need to reach HuggingFace Hub at runtime. We set these flags only for the
    # duration of the Kokoro import/init so we don't interfere with other model
    # downloads (e.g. Whisper STT) that DO need network access.
    _prev_hf_offline = os.environ.get("HF_HUB_OFFLINE")
    _prev_tf_offline = os.environ.get("TRANSFORMERS_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    t0 = time.time()
    try:
        from kokoro import KPipeline
        logger.info("  ✓ KPipeline imported")

        logger.info("  Creating pipeline (may take 30-60s on first run)...")

        try:
            # Kokoro emits a repo_id warning via print() to stderr — redirect to suppress it
            _stderr_capture = io.StringIO()
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=r".*Defaulting repo_id.*")
                warnings.filterwarnings("ignore", message=r".*dropout option.*")
                warnings.filterwarnings("ignore", message=r".*weight_norm.*")
                _real_stderr, sys.stderr = sys.stderr, _stderr_capture
                try:
                    _pipeline = KPipeline(lang_code="a")
                finally:
                    sys.stderr = _real_stderr
            elapsed = time.time() - t0
            logger.info(f"  ✓ Pipeline created ({elapsed:.1f}s)")
        except Exception as e:
            logger.exception(f"  ✗ Pipeline creation failed: {e}")
            raise
    finally:
        # Always restore the previous HF_HUB_OFFLINE state so other loaders
        # (e.g. Whisper) are not blocked from downloading their models.
        if _prev_hf_offline is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = _prev_hf_offline

        if _prev_tf_offline is None:
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
        else:
            os.environ["TRANSFORMERS_OFFLINE"] = _prev_tf_offline

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


def _synthesise_one(sentence: str) -> bytes | None:
    """
    Synthesise a single sentence in a thread-safe, blocking call.
    Returns raw Int16 PCM bytes, or None if synthesis produced no audio.
    """
    if _pipeline is None:
        raise RuntimeError("TTS model not loaded — call load_tts_model() first")

    audio_chunks = list(_pipeline(sentence, voice=VOICE))
    if not audio_chunks:
        return None

    audio_arrays = [c[2] for c in audio_chunks if c[2] is not None]
    if not audio_arrays:
        return None

    audio = np.concatenate(audio_arrays)
    return (audio * 32767).astype(np.int16).tobytes()


def synthesise(text: str) -> list[bytes]:
    """
    Synchronous bulk version — synthesise full response, return list of Int16 PCM chunks.
    Kept for backward compatibility; the streaming hot path uses synthesise_stream().
    """
    sentences = _split_sentences(text)
    logger.info(f"TTS: {len(sentences)} sentence(s), {len(text)} chars")

    result = []
    for i, sentence in enumerate(sentences, 1):
        t0 = time.time()
        pcm = _synthesise_one(sentence)
        if pcm:
            result.append(pcm)
            logger.debug(f"TTS: sentence {i}/{len(sentences)} ({time.time()-t0:.2f}s) → {len(pcm)} bytes")

    return result


async def synthesise_stream(text: str) -> AsyncIterator[bytes]:
    """
    TRUE sentence-streaming async generator.

    Splits the response into sentences and synthesises each one in a thread
    executor, yielding PCM bytes as soon as each sentence is ready.  This
    means the first audio chunk arrives after ~1-2s (one sentence) rather
    than waiting for all sentences to finish (~9s for 4 sentences).

    The caller (WebSocket handler) can start sending audio to the client
    immediately while the remaining sentences are still being synthesised.
    """
    if _pipeline is None:
        raise RuntimeError("TTS model not loaded — call load_tts_model() first")

    sentences = _split_sentences(text)
    logger.info(f"TTS: {len(sentences)} sentence(s), {len(text)} chars")

    loop = asyncio.get_event_loop()
    for i, sentence in enumerate(sentences, 1):
        t0 = time.time()
        pcm = await loop.run_in_executor(None, _synthesise_one, sentence)
        elapsed = time.time() - t0
        if pcm:
            logger.debug(
                f"TTS: sentence {i}/{len(sentences)} ({elapsed:.2f}s) "
                f"→ {len(pcm)} bytes — yielding"
            )
            yield pcm
        else:
            logger.warning(f"TTS: sentence {i}/{len(sentences)} produced no audio — skipping")