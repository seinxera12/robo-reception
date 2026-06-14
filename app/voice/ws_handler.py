import asyncio
import json
import logging
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.voice.vad import VADProcessor
from app.voice.stt import transcribe
from app.voice.tts import synthesise_stream
from app.session.manager import SessionManager
from app.agent.core import run_agent
from app.agent.models import RoboDeps

logger = logging.getLogger(__name__)
router = APIRouter()


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

        _chunk_count = 0
        _speaking_logged = False

        async for message in websocket.iter_bytes():
            try:
                _chunk_count += 1

                # Log first chunk and then every 200 to prove data is arriving
                if _chunk_count == 1:
                    logger.info(f"  ← First PCM chunk received: {len(message)} bytes")
                elif _chunk_count % 200 == 0:
                    logger.info(f"  ← PCM chunks received: {_chunk_count}, last chunk: {len(message)} bytes")

                # ── VAD ───────────────────────────────────────────────────────
                is_speaking, utterance_bytes = vad.process_chunk(message)

                if is_speaking and not _speaking_logged:
                    logger.info("  VAD: speech detected — listening")
                    _speaking_logged = True
                    await send_json({"type": "state", "state": "listening"})
                elif is_speaking:
                    await send_json({"type": "state", "state": "listening"})
                elif not is_speaking and _speaking_logged:
                    # Speech ended (silence threshold) but no utterance yet
                    pass

                if utterance_bytes is None:
                    continue

                # Utterance complete — reset speaking flag for next one
                _speaking_logged = False
                logger.info(f"  VAD: utterance complete — {len(utterance_bytes)} bytes")

                # ── STT ───────────────────────────────────────────────────────
                await send_json({"type": "state", "state": "thinking"})
                logger.info("  STT: transcribing utterance...")

                t_utterance_end = time.time()
                # transcribe blocks — run in thread so event loop stays free
                transcript = await asyncio.to_thread(transcribe, utterance_bytes)
                t_stt_done = time.time()

                if not transcript.strip():
                    logger.warning("  STT: empty result, back to idle")
                    await send_json({"type": "state", "state": "idle"})
                    continue

                logger.info(f"  STT ({t_stt_done - t_utterance_end:.2f}s): '{transcript}'")
                await send_json({"type": "transcript", "text": transcript})

                # ── Agent ─────────────────────────────────────────────────────
                session_data = await session_manager.get(kiosk_id, session_uuid) or {}

                deps = RoboDeps(
                    kiosk_id=kiosk_id,
                    session_uuid=session_uuid,
                    visitor_name=session_data.get("visitor_name"),
                    current_appointment_id=session_data.get("current_appointment_id"),
                )
                conversation_history = session_data.get("conversation_history", [])

                response_text = await run_agent(transcript, deps, conversation_history)
                t_agent_done = time.time()
                logger.info(
                    f"  Agent ({t_agent_done - t_stt_done:.2f}s): '{response_text[:80]}'"
                )

                # Persist session — conversation history serialisation is Day 4
                await session_manager.update(kiosk_id, session_uuid, {})

                # ── TTS (streaming) ───────────────────────────────────────────
                await send_json({"type": "response", "text": response_text})
                await send_json({"type": "state", "state": "speaking"})
                logger.info("  TTS: streaming...")

                first_chunk = True
                async for audio_chunk in synthesise_stream(response_text):
                    if first_chunk:
                        t_first_tts = time.time()
                        logger.info(
                            f"  LATENCY — STT: {t_stt_done - t_utterance_end:.2f}s | "
                            f"Agent: {t_agent_done - t_stt_done:.2f}s | "
                            f"TTS first byte: {t_first_tts - t_agent_done:.2f}s | "
                            f"Total: {t_first_tts - t_utterance_end:.2f}s"
                        )
                        first_chunk = False
                    await websocket.send_bytes(audio_chunk)

                logger.info("  TTS: complete")
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
