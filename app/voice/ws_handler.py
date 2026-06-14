import asyncio
import json
import logging
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic_ai.messages import ModelMessagesTypeAdapter
import redis.asyncio as aioredis

from app.voice.vad import VADProcessor
from app.voice.stt import transcribe
from app.voice.tts import synthesise_stream
from app.session.manager import SessionManager
from app.agent.core import run_agent
from app.agent.models import RoboDeps

logger = logging.getLogger(__name__)
router = APIRouter()

# Sentinel object: putting this into the send queue signals the writer to stop.
_STOP = object()


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

    # ── Dedicated pubsub client ───────────────────────────────────────────────
    # hiredis (installed via redis[hiredis]) has a known incompatibility with
    # asyncio pubsub: its parser does not properly yield between listen() calls,
    # causing published messages to be silently dropped. We use a separate client
    # with the pure-Python RESP2 parser for the subscription connection only.
    #
    # socket_keepalive=True prevents the TCP connection from going silently stale
    # when the host acknowledgement arrives minutes after the check-in; without it
    # the OS/firewall can tear down the idle TCP connection and pubsub.listen()
    # hangs forever, never receiving the event.
    from app.config import settings as _settings
    from redis.asyncio.connection import _AsyncRESP2Parser
    _pubsub_redis = aioredis.from_url(
        _settings.redis_url,
        decode_responses=True,
        parser_class=_AsyncRESP2Parser,
        socket_keepalive=True,
    )

    # ── [DIAG] Verify Redis connectivity at connection time ──────────────────
    # Catches misconfiguration, wrong URL, or Redis being down before we
    # invest in the full session/VAD setup.
    try:
        pong = await _pubsub_redis.ping()
        logger.info(f"  [DIAG] pubsub redis PING → {pong}  url={_settings.redis_url}")
    except Exception as _ping_err:
        logger.error(f"  [DIAG] pubsub redis PING FAILED: {_ping_err}  url={_settings.redis_url}")

    try:
        session_uuid = await session_manager.create(kiosk_id)
        logger.debug(f"  Session: {session_uuid}")
    except Exception as e:
        logger.exception(f"✗ Session creation failed: {e}")
        await websocket.close(code=1011)
        return

    vad = VADProcessor()

    # ── Serialised send queue ─────────────────────────────────────────────────
    # Starlette WebSockets are NOT concurrent-send-safe. Both the audio loop and
    # the Redis listener need to send frames, so we funnel everything through a
    # single asyncio.Queue consumed by one dedicated writer coroutine.
    # Items are either:
    #   dict  → serialised to JSON text frame
    #   bytes → sent as binary frame
    #   _STOP → writer exits cleanly
    _send_queue: asyncio.Queue = asyncio.Queue()

    async def ws_writer():
        """Single coroutine that owns all websocket.send_* calls."""
        while True:
            item = await _send_queue.get()
            if item is _STOP:
                logger.info("  [DIAG] ws_writer: received STOP sentinel — exiting")
                break
            try:
                if isinstance(item, bytes):
                    await websocket.send_bytes(item)
                else:
                    text_frame = json.dumps(item)
                    await websocket.send_text(text_frame)
                    # Only log non-audio control frames to avoid flooding
                    if isinstance(item, dict) and item.get("type") in ("ui_update", "state", "transcript", "response"):
                        logger.info(
                            f"  [DIAG] ws_writer: sent type={item.get('type')!r}"
                            + (f" event={item.get('event')!r}" if "event" in item else "")
                            + (f" state={item.get('state')!r}" if "state" in item else "")
                        )
            except Exception as e:
                logger.error(
                    f"  [DIAG] ws_writer: SEND FAILED — frame will NOT reach browser: {e}  "
                    f"item_type={type(item).__name__}"
                )

    def send_json(payload: dict):
        """Non-blocking enqueue of a JSON text frame."""
        _send_queue.put_nowait(payload)

    def send_bytes(data: bytes):
        """Non-blocking enqueue of a binary frame."""
        _send_queue.put_nowait(data)

    # ── Task 1: WebSocket writer ──────────────────────────────────────────────
    writer_task = asyncio.create_task(ws_writer())

    # ── Task 2: Redis pub/sub listener ────────────────────────────────────────
    # _subscribed is set once the SUBSCRIBE confirmation arrives from Redis.
    # audio_loop() awaits this event before proceeding — eliminating the race
    # where agent tools publish events before the subscription is confirmed.
    _subscribed = asyncio.Event()

    async def redis_listener():
        pubsub = _pubsub_redis.pubsub()
        logger.info("  [DIAG] pubsub: sending SUBSCRIBE robo:events")
        await pubsub.subscribe("robo:events")

        try:
            async for message in pubsub.listen():
                msg_type = message.get("type")

                # The first message back from Redis is the subscribe confirmation
                # (type == "subscribe").  Signal the audio loop that we're ready
                # before doing anything else.
                if msg_type == "subscribe":
                    _subscribed.set()
                    logger.info(
                        f"  [DIAG] pubsub: SUBSCRIBE confirmed "
                        f"channel={message.get('channel')!r} "
                        f"active_subs={message.get('data')}"
                    )
                    continue

                # pong frames arrive if health-check PINGs are sent on the
                # pubsub connection — not messages, just keepalive traffic.
                if msg_type == "pong":
                    logger.debug("  [DIAG] pubsub: keepalive pong received")
                    continue

                if msg_type != "message":
                    logger.debug(f"  [DIAG] pubsub: ignored frame type={msg_type!r}")
                    continue

                # ── Real event payload ────────────────────────────────────
                raw = message.get("data", "")
                logger.info(
                    f"  [DIAG] pubsub: MESSAGE received "
                    f"channel={message.get('channel')!r} raw={raw[:120]!r}"
                )

                try:
                    event = json.loads(raw)
                except json.JSONDecodeError as _je:
                    logger.error(f"  [DIAG] pubsub: JSON decode failed: {_je}  raw={raw!r}")
                    continue

                event_type = event.get("type", "<missing>")
                logger.info(f"  [DIAG] pubsub: dispatching event_type={event_type!r}")

                if event_type == "host_acknowledged":
                    payload = {
                        "type": "ui_update",
                        "event": "host_acknowledged",
                        "host_name": event["host_name"],
                        "visitor_name": event["visitor_name"],
                        "appointment_id": event["appointment_id"],
                    }
                    send_json(payload)
                    logger.info(
                        f"  [DIAG] ui_update enqueued: host_acknowledged "
                        f"visitor={event.get('visitor_name')!r} "
                        f"queue_size={_send_queue.qsize()}"
                    )

                elif event_type == "checkin_complete":
                    payload = {
                        "type": "ui_update",
                        "event": "checkin_complete",
                        "appointment_id": event["appointment_id"],
                    }
                    send_json(payload)
                    logger.info(
                        f"  [DIAG] ui_update enqueued: checkin_complete "
                        f"queue_size={_send_queue.qsize()}"
                    )

                elif event_type == "notification_sent":
                    payload = {
                        "type": "ui_update",
                        "event": "notification_sent",
                        "appointment_id": event["appointment_id"],
                        "host_name": event["host_name"],
                    }
                    send_json(payload)
                    logger.info(
                        f"  [DIAG] ui_update enqueued: notification_sent "
                        f"host={event.get('host_name')!r} "
                        f"queue_size={_send_queue.qsize()}"
                    )

                else:
                    logger.warning(f"  [DIAG] pubsub: unhandled event_type={event_type!r}")

        except asyncio.CancelledError:
            logger.info("  [DIAG] pubsub: listener task cancelled — cleaning up")
            await pubsub.unsubscribe("robo:events")
            await pubsub.aclose()
            await _pubsub_redis.aclose()
            logger.info("  Redis pub/sub unsubscribed")
            raise
        except Exception as _listener_err:
            # Any unexpected exception here means the listener is dead — log it
            # loudly so it's visible even if the audio loop is still running.
            logger.exception(
                f"  [DIAG] pubsub: listener crashed — events will no longer reach browser: {_listener_err}"
            )
            raise

    # ── Task 3: Audio receive + agent loop ────────────────────────────────────
    async def audio_loop():
        # Wait for the Redis subscription to be confirmed before proceeding.
        # This closes the race where agent tools publish events before the
        # listener has finished the SUBSCRIBE handshake with Redis, which
        # causes those events to be silently dropped.
        logger.info("  [DIAG] audio_loop: waiting for pubsub subscription confirmation…")
        try:
            await asyncio.wait_for(_subscribed.wait(), timeout=5.0)
            logger.info("  [DIAG] audio_loop: pubsub ready — proceeding")
        except asyncio.TimeoutError:
            logger.error(
                "  [DIAG] audio_loop: TIMEOUT waiting for pubsub SUBSCRIBE confirmation "
                "(>5s) — Redis may be unreachable or the listener task crashed"
            )
            # Don't abort — continue anyway so the kiosk isn't bricked,
            # but badge updates will not work until this is resolved.

        send_json({"type": "state", "state": "idle"})
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
                    send_json({"type": "state", "state": "listening"})
                elif is_speaking:
                    send_json({"type": "state", "state": "listening"})
                elif not is_speaking and _speaking_logged:
                    pass  # speech ended but utterance not yet complete

                if utterance_bytes is None:
                    continue

                # Utterance complete
                _speaking_logged = False
                logger.info(f"  VAD: utterance complete — {len(utterance_bytes)} bytes")

                # ── STT ───────────────────────────────────────────────────
                send_json({"type": "state", "state": "thinking"})

                t_utterance_end = time.time()
                transcript = await asyncio.to_thread(transcribe, utterance_bytes)
                t_stt_done = time.time()

                if not transcript.strip():
                    logger.warning("  STT: empty transcript, back to idle")
                    send_json({"type": "state", "state": "idle"})
                    continue

                logger.info(f"  STT ({t_stt_done - t_utterance_end:.2f}s): '{transcript}'")
                send_json({"type": "transcript", "text": transcript})

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
                if isinstance(conversation_history_raw, str) and conversation_history_raw:
                    conversation_history = ModelMessagesTypeAdapter.validate_json(
                        conversation_history_raw
                    )
                else:
                    conversation_history = []

                response_text, agent_result = await run_agent(transcript, deps, conversation_history)
                t_agent_done = time.time()

                # Persist conversation history
                history_json: str = (
                    agent_result.all_messages_json().decode("utf-8")
                    if agent_result else "[]"
                )
                await session_manager.update(kiosk_id, session_uuid, {
                    "conversation_history": history_json,
                })

                # ── TTS (streaming) ───────────────────────────────────────
                send_json({"type": "response", "text": response_text})
                send_json({"type": "state", "state": "speaking"})

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
                    send_bytes(audio_chunk)

                logger.info("  TTS: done")
                send_json({"type": "audio_end"})
                send_json({"type": "state", "state": "idle"})

            except Exception as e:
                logger.exception(f"✗ Error in voice loop: {e}")
                send_json({"type": "state", "state": "idle"})

    # ── Run all tasks concurrently ────────────────────────────────────────────
    # Start the listener first so its subscribe handshake is in-flight while
    # audio_loop() awaits _subscribed.  This guarantees no events are lost.
    listener_task = asyncio.create_task(redis_listener())
    logger.info(f"  [DIAG] tasks created: writer={writer_task!r} listener={listener_task!r}")
    try:
        await audio_loop()
    except WebSocketDisconnect:
        logger.info(f"✓ WebSocket disconnected: kiosk={kiosk_id}")
    except Exception as e:
        logger.exception(f"✗ WebSocket error: {e}")
    finally:
        # Stop the writer and listener cleanly
        listener_task.cancel()
        _send_queue.put_nowait(_STOP)
        await asyncio.gather(writer_task, listener_task, return_exceptions=True)
        try:
            await session_manager.delete(kiosk_id, session_uuid)
        except Exception:
            pass
