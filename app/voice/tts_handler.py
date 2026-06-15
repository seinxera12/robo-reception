# app/voice/tts_handler.py
"""
HTTP endpoint for on-demand TTS synthesis.
Used by the chat panel to speak agent responses.

Streams raw Int16 PCM audio (24 kHz mono) sentence-by-sentence so the
browser can start playing the first sentence while the rest is synthesised —
matching the latency of the voice WebSocket pipeline.
"""
import asyncio
import logging
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.voice.tts import synthesise_stream

logger = logging.getLogger(__name__)
router = APIRouter()


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


async def _stream_pcm(text: str) -> AsyncIterator[bytes]:
    """
    Yield PCM chunks as they come off the synthesiser.
    synthesise_stream() splits the text into sentences and yields each
    sentence's audio as soon as it's ready — so playback can begin before
    the full response is synthesised.
    """
    had_audio = False
    async for chunk in synthesise_stream(text):
        had_audio = True
        yield chunk
    if not had_audio:
        # Yield two bytes of silence so the browser never gets an empty body
        yield b"\x00\x00"


@router.post("/tts")
async def tts_synthesise(body: TTSRequest) -> StreamingResponse:
    """
    Synthesise text and stream raw Int16 PCM audio (24 kHz mono).

    The response body is a chunked binary stream. The client should read it
    with the Fetch Streams API, decoding and playing each chunk as it arrives
    rather than waiting for the full body (arrayBuffer).
    """
    logger.info(f"TTS HTTP: streaming {len(body.text)} chars")

    return StreamingResponse(
        _stream_pcm(body.text),
        media_type="application/octet-stream",
        headers={
            "X-Sample-Rate": "24000",
            "X-Encoding": "pcm_s16le",
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",   # disable nginx buffering — same as SSE
        },
    )
