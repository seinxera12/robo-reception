import asyncio
import json
import logging
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic_ai.messages import ModelMessagesTypeAdapter

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

    # ── Task 1: Redis pub/sub listener ────────────────────────────────────────
    # Runs concurrently with the audio loop so host-acknowledgement events can
    # push browser UI updates without polling.
    async def redis_listener():
        pubsub = redis.pubsub()
        await pubsub.subscribe("robo:events")
        logger.info("  Redis pub/sub subscribed: robo:events")

        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                event = json.loads(message["data"])
                logger.info(f"  Redis event received: {event['type']}")

                if event["type"] == "host_acknowledged":
                    await send_json({
                        "type": "ui_update",
                        "event": "host_acknowledged",
                        "host_name": event["host_name"],
                        "visitor_name": event["visitor_name"],
                        "appointment_id": event["appointment_id"],
                    })
                    logger.info("  ✓ Host acknowledged event sent to browser")

                elif event["type"] == "checkin_complete":
                    await send_json({
                        "type": "ui_update",
                        "event": "checkin_complete",
                        "appointment_id": event["appointment_id"],
                    })

                elif event["type"] == "notification_sent":
                    await send_json({
                        "type": "ui_update",
                        "event": "notification_sent",
                        "appointment_id": event["appointment_id"],
                        "host_name": event["host_name"],
                    })

        except asyncio.CancelledError:
            await pubsub.unsubscribe("robo:events")
            logger.info("  Redis pub/sub unsubscribed")
            raise

    # ── Task 2: Audio receive + agent loop ────────────────────────────────────
    async def audio_loop():
        await send_json({"type": "state", "state": "idle"})
        logger.info("  Voice loop started")

        _chunk_count = 0
        _speaking_logged = False

        async for message in websocket.iter_bytes():
            try:
                _chunk_count += 1

                if _chunk_count == 1:
                    logger.info(f"  ← First PCM chunk received: {len(message)} bytes")
                elif _chunk_count % 200 == 0:
                    logger.info(f"  ← PCM chunks received: {_chunk_count}, last chunk: {len(message)} bytes")

                # ── VAD ───────────────────────────────────────────────────
                is_speaking, utterance_bytes = vad.process_chunk(message)

                if is_speaking and not _speaking_logged:
                    logger.info("  VAD: speech detected — listening")
                    _speaking_logged = True
                    await send_json({"type": "state", "state": "listening"})
                elif is_speaking:
                    await send_json({"type": "state", "state": "listening"})
                elif not is_speaking and _speaking_logged:
                    pass  # speech ended but utterance not yet complete

                if utterance_bytes is None:
                    continue

                # Utterance complete
                _speaking_logged = False
                logger.info(f"  VAD: utterance complete — {len(utterance_bytes)} bytes")

                # ── STT ───────────────────────────────────────────────────
                await send_json({"type": "state", "state": "thinking"})

                t_utterance_end = time.time()
                transcript = await asyncio.to_thread(transcribe, utterance_bytes)
                t_stt_done = time.time()

                if not transcript.strip():
                    logger.warning("  STT: empty transcript, back to idle")
                    await send_json({"type": "state", "state": "idle"})
                    continue

                logger.info(f"  STT ({t_stt_done - t_utterance_end:.2f}s): '{transcript}'")
                await send_json({"type": "transcript", "text": transcript})

                # ── Agent ─────────────────────────────────────────────────
                session_data = await session_manager.get(kiosk_id, session_uuid) or {}

                deps = RoboDeps(
                    kiosk_id=kiosk_id,
                    session_uuid=session_uuid,
                    visitor_name=session_data.get("visitor_name"),
                    current_appointment_id=session_data.get("current_appointment_id"),
                    redis=redis,  # tools use this to publish badge events
                )
                conversation_history_raw = session_data.get("conversation_history", "[]")
                # Deserialize: stored as a JSON string (bytes decoded), restore to model list
                if isinstance(conversation_history_raw, str) and conversation_history_raw:
                    conversation_history = ModelMessagesTypeAdapter.validate_json(
                        conversation_history_raw
                    )
                else:
                    conversation_history = []

                response_text, agent_result = await run_agent(transcript, deps, conversation_history)
                t_agent_done = time.time()

                # Persist conversation history so context carries across utterances.
                # all_messages_json() returns bytes (pydantic dump_json) — decode to str
                # so json.dumps() in session_manager.update() can serialize it as a string.
                history_json: str = (
                    agent_result.all_messages_json().decode("utf-8")
                    if agent_result else "[]"
                )
                await session_manager.update(kiosk_id, session_uuid, {
                    "conversation_history": history_json,
                })

                # ── TTS (streaming) ───────────────────────────────────────
                await send_json({"type": "response", "text": response_text})
                await send_json({"type": "state", "state": "speaking"})

                first_chunk = True
                async for audio_chunk in synthesise_stream(response_text):
                    if first_chunk:
                        t_first_tts = time.time()
                        logger.info(
                            f"  LATENCY  : STT {t_stt_done - t_utterance_end:.2f}s"
                            f" | agent {t_agent_done - t_stt_done:.2f}s"
                            f" | TTS {t_first_tts - t_agent_done:.2f}s"
                            f" | total {t_first_tts - t_utterance_end:.2f}s"
                        )
                        first_chunk = False
                    await websocket.send_bytes(audio_chunk)

                logger.info("  TTS: done")
                await send_json({"type": "audio_end"})
                await send_json({"type": "state", "state": "idle"})

            except Exception as e:
                logger.exception(f"✗ Error in voice loop: {e}")
                await send_json({"type": "state", "state": "idle"})

    # ── Run both tasks concurrently ───────────────────────────────────────────
    # The Redis listener is a background task — it gets cancelled cleanly when
    # the WebSocket disconnects (audio_loop exits).
    listener_task = asyncio.create_task(redis_listener())
    try:
        await audio_loop()
    except WebSocketDisconnect:
        logger.info(f"✓ WebSocket disconnected: kiosk={kiosk_id}")
    except Exception as e:
        logger.exception(f"✗ WebSocket error: {e}")
    finally:
        listener_task.cancel()
        await asyncio.gather(listener_task, return_exceptions=True)
        try:
            await session_manager.delete(kiosk_id, session_uuid)
        except Exception:
            pass
