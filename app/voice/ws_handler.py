import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.voice.vad import VADProcessor
from app.voice.stt import transcribe
from app.voice.tts import synthesise
from app.session.manager import SessionManager

logger = logging.getLogger(__name__)
router = APIRouter()

HARDCODED_RESPONSE = (
    "Thank you, I heard you. I am Robo, your reception assistant. "
    "I will be able to look up your appointment and notify your host very soon."
)


@router.websocket("/ws/voice/{kiosk_id}")
async def voice_endpoint(websocket: WebSocket, kiosk_id: str):
    try:
        await websocket.accept()
        logger.info(f"✓ WebSocket connected: kiosk={kiosk_id} client={websocket.client}")
    except Exception as e:
        logger.exception(f"✗ WebSocket accept failed: {e}")
        return

    redis = websocket.app.state.redis
    session_manager = SessionManager(redis)

    try:
        session_uuid = await session_manager.create(kiosk_id)
        logger.debug(f"  Session: {session_uuid}")
    except Exception as e:
        logger.exception(f"✗ Session creation failed: {e}")
        await websocket.close(code=1011)
        return

    vad = VADProcessor()

    async def send_json(payload: dict):
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception as e:
            logger.error(f"✗ send_json failed: {e}")

    try:
        await send_json({"type": "state", "state": "idle"})
        logger.info("  Voice loop started")

        async for message in websocket.iter_bytes():
            try:
                # ── VAD ───────────────────────────────────────────────────────
                is_speaking, utterance_bytes = vad.process_chunk(message)

                if is_speaking:
                    await send_json({"type": "state", "state": "listening"})

                if utterance_bytes is None:
                    continue

                # ── STT ───────────────────────────────────────────────────────
                await send_json({"type": "state", "state": "thinking"})
                logger.info("  STT: transcribing utterance...")

                # transcribe blocks — run in thread so event loop stays free
                transcript = await asyncio.to_thread(transcribe, utterance_bytes)

                if not transcript.strip():
                    logger.warning("  STT: empty result, back to idle")
                    await send_json({"type": "state", "state": "idle"})
                    continue

                logger.info(f"  STT: '{transcript}'")
                await send_json({"type": "transcript", "text": transcript})

                # ── Response ──────────────────────────────────────────────────
                response_text = HARDCODED_RESPONSE
                await send_json({"type": "response", "text": response_text})

                # ── TTS ───────────────────────────────────────────────────────
                await send_json({"type": "state", "state": "speaking"})
                logger.info("  TTS: synthesizing...")

                # synthesise blocks — run in thread, returns all PCM at once
                pcm_chunks = await asyncio.to_thread(synthesise, response_text)

                for i, chunk in enumerate(pcm_chunks, 1):
                    await websocket.send_bytes(chunk)
                    logger.debug(f"  TTS: sent chunk {i}/{len(pcm_chunks)} ({len(chunk)} bytes)")

                logger.info(f"  TTS: complete ({len(pcm_chunks)} chunks)")
                await send_json({"type": "audio_end"})
                await send_json({"type": "state", "state": "idle"})

            except Exception as e:
                logger.exception(f"✗ Error in voice loop: {e}")
                await send_json({"type": "state", "state": "idle"})

    except WebSocketDisconnect:
        logger.info(f"✓ WebSocket disconnected: kiosk={kiosk_id}")
    except Exception as e:
        logger.exception(f"✗ WebSocket error: {e}")
    finally:
        try:
            await session_manager.delete(kiosk_id, session_uuid)
        except Exception:
            pass
