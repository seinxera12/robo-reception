import asyncio
import json
import logging
import time
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic_ai.messages import ModelMessagesTypeAdapter
import redis.asyncio as aioredis

from app.voice.vad import VADProcessor
from app.voice.stt import transcribe
from app.voice.tts import synthesise_stream, synthesise
from app.session.manager import SessionManager
from app.agent.core import run_agent
from app.agent.models import RoboDeps

logger = logging.getLogger(__name__)
router = APIRouter()

# Sentinel object: putting this into the send queue signals the writer to stop.
_STOP = object()

# How often (seconds) the pubsub poll loop yields without a message.
# Keeps the event loop responsive without burning CPU.
_PUBSUB_POLL_INTERVAL = 0.05


@router.websocket("/ws/voice/{kiosk_id}")
async def voice_endpoint(
    websocket: WebSocket,
    kiosk_id: str,
    session_uuid: str | None = Query(default=None),
):
    try:
        await websocket.accept()
        logger.info(f"✓ WebSocket connected: kiosk={kiosk_id} client={websocket.client}")
    except Exception as e:
        logger.exception(f"✗ WebSocket accept failed: {e}")
        return

    redis = websocket.app.state.redis
    session_manager = SessionManager(redis)

    # ── Dedicated pubsub client ───────────────────────────────────────────────
    # hiredis has a known asyncio incompatibility (messages silently dropped).
    # We use the pure-Python RESP2 parser for pubsub only.
    # socket_keepalive=True prevents the OS from tearing down an idle TCP
    # connection while waiting for the host to tap the acknowledge link.
    from app.config import settings as _settings
    from redis.asyncio.connection import _AsyncRESP2Parser
    _pubsub_redis = aioredis.from_url(
        _settings.redis_url,
        decode_responses=True,
        parser_class=_AsyncRESP2Parser,
        socket_keepalive=True,
    )

    try:
        pong = await _pubsub_redis.ping()
        logger.info(f"  [DIAG] pubsub redis PING → {pong}  url={_settings.redis_url}")
    except Exception as _ping_err:
        logger.error(f"  [DIAG] pubsub redis PING FAILED: {_ping_err}  url={_settings.redis_url}")

    # ── Session setup ─────────────────────────────────────────────────────────
    try:
        if session_uuid:
            existing = await session_manager.get(kiosk_id, session_uuid)
            if existing is not None:
                logger.info(
                    f"  Voice: reusing existing session {session_uuid!r} "
                    f"for kiosk={kiosk_id}"
                )
            else:
                logger.warning(
                    f"  Voice: session_uuid={session_uuid!r} not found "
                    f"— creating new session"
                )
                session_uuid = await session_manager.create(kiosk_id)
        else:
            session_uuid = await session_manager.create(kiosk_id)
        logger.debug(f"  Session: {session_uuid}")
    except Exception as e:
        logger.exception(f"✗ Session creation failed: {e}")
        await websocket.close(code=1011)
        return

    vad = VADProcessor()

    # ── Serialised send queue ─────────────────────────────────────────────────
    # Starlette WebSockets are NOT concurrent-send-safe. All senders (audio loop
    # and Redis listener) funnel through this queue → one writer task.
    # Items: dict → JSON text frame | bytes → binary frame | _STOP → exit
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
                    if isinstance(item, dict) and item.get("type") in (
                        "ui_update", "state", "transcript", "response", "tts_chunk_done"
                    ):
                        logger.info(
                            f"  [DIAG] ws_writer: sent type={item.get('type')!r}"
                            + (f" event={item.get('event')!r}" if "event" in item else "")
                            + (f" state={item.get('state')!r}" if "state" in item else "")
                        )
            except Exception as e:
                logger.error(
                    f"  [DIAG] ws_writer: SEND FAILED: {e}  "
                    f"item_type={type(item).__name__}"
                )

    def send_json(payload: dict):
        """Non-blocking enqueue of a JSON text frame."""
        _send_queue.put_nowait(payload)

    def send_bytes(data: bytes):
        """Non-blocking enqueue of a binary frame."""
        _send_queue.put_nowait(data)

    async def speak(text: str) -> None:
        """
        Synthesise text and stream it through the send queue.
        Safe to call from any coroutine — synthesis runs in a thread executor
        so it never blocks the event loop.
        """
        logger.info(f"  [TTS] speak(): synthesising {len(text)} chars")
        send_json({"type": "state", "state": "speaking"})
        try:
            audio_chunks = await asyncio.to_thread(synthesise, text)
            for chunk in audio_chunks:
                send_bytes(chunk)
            send_json({"type": "audio_end"})
            send_json({"type": "state", "state": "idle"})
            logger.info("  [TTS] speak(): done")
        except Exception as _tts_err:
            logger.error(f"  [TTS] speak(): synthesis failed — {_tts_err}")
            send_json({"type": "state", "state": "idle"})

    # ── Task 1: WebSocket writer ──────────────────────────────────────────────
    writer_task = asyncio.create_task(ws_writer())

    # ── Task 2: Redis pub/sub listener ────────────────────────────────────────
    # WHY get_message() polling instead of `async for pubsub.listen()`:
    # `listen()` holds an async socket-read inside the iterator between yields.
    # When we `await run_in_executor(synthesise)` inside the loop body, the
    # iterator's internal socket-read is still outstanding on the same connection
    # and the two awaitables fight for the event loop — messages get dropped or
    # the synthesise call never completes.  get_message() with a short timeout
    # yields cleanly between polls and is the same pattern the SSE handler uses.
    _subscribed = asyncio.Event()

    async def redis_listener():
        pubsub = _pubsub_redis.pubsub()
        logger.info("  [DIAG] pubsub: sending SUBSCRIBE robo:events")
        await pubsub.subscribe("robo:events")

        try:
            # Drain the subscribe-confirmation frame first so _subscribed is set
            # before audio_loop() starts sending audio.
            while not _subscribed.is_set():
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=False, timeout=1.0
                )
                if msg and msg.get("type") == "subscribe":
                    _subscribed.set()
                    logger.info(
                        f"  [DIAG] pubsub: SUBSCRIBE confirmed "
                        f"channel={msg.get('channel')!r} "
                        f"active_subs={msg.get('data')}"
                    )

            # Main poll loop — yields every _PUBSUB_POLL_INTERVAL seconds
            # whether or not a message arrived.
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=_PUBSUB_POLL_INTERVAL,
                )

                if msg is None:
                    continue  # no message this tick — yield and poll again

                if msg.get("type") != "message":
                    logger.debug(f"  [DIAG] pubsub: ignored frame type={msg.get('type')!r}")
                    continue

                raw = msg.get("data", "")
                logger.info(
                    f"  [DIAG] pubsub: MESSAGE received raw={raw[:120]!r}"
                )

                try:
                    event = json.loads(raw)
                except json.JSONDecodeError as _je:
                    logger.error(f"  [DIAG] pubsub: JSON decode failed: {_je}")
                    continue

                event_type = event.get("type", "<missing>")
                event_session = event.get("session_uuid")

                logger.info(
                    f"  [DIAG] pubsub: dispatching event_type={event_type!r} "
                    f"event_session={event_session!r} our_session={session_uuid!r}"
                )

                # ── host_acknowledged ─────────────────────────────────────
                if event_type == "host_acknowledged":
                    # Only announce for our session — multiple kiosks may be
                    # subscribed to the same channel.
                    if event_session and event_session != session_uuid:
                        logger.debug(
                            f"  [DIAG] pubsub: host_acknowledged skipped "
                            f"(session mismatch)"
                        )
                        continue

                    host_name     = event["host_name"]
                    visitor_name  = event["visitor_name"]
                    announce_text = f"{host_name} is on their way to meet you."

                    send_json({
                        "type": "ui_update",
                        "event": "host_acknowledged",
                        "host_name": host_name,
                        "visitor_name": visitor_name,
                        "appointment_id": event["appointment_id"],
                    })
                    logger.info(
                        f"  [DIAG] ui_update enqueued: host_acknowledged "
                        f"visitor={visitor_name!r}"
                    )

                    # Speak the announcement — runs synthesis in a thread,
                    # streams audio chunks through the send queue.
                    await speak(announce_text)

                # ── checkin_complete ──────────────────────────────────────
                elif event_type == "checkin_complete":
                    if event_session and event_session != session_uuid:
                        continue
                    send_json({
                        "type": "ui_update",
                        "event": "checkin_complete",
                        "appointment_id": event["appointment_id"],
                    })
                    logger.info(
                        f"  [DIAG] ui_update enqueued: checkin_complete"
                    )

                # ── notification_sent ─────────────────────────────────────
                elif event_type == "notification_sent":
                    if event_session and event_session != session_uuid:
                        continue
                    send_json({
                        "type": "ui_update",
                        "event": "notification_sent",
                        "appointment_id": event["appointment_id"],
                        "host_name": event["host_name"],
                    })
                    logger.info(
                        f"  [DIAG] ui_update enqueued: notification_sent "
                        f"host={event.get('host_name')!r}"
                    )

                else:
                    logger.warning(
                        f"  [DIAG] pubsub: unhandled event_type={event_type!r}"
                    )

        except asyncio.CancelledError:
            logger.info("  [DIAG] pubsub: listener task cancelled — cleaning up")
            await pubsub.unsubscribe("robo:events")
            await pubsub.aclose()
            await _pubsub_redis.aclose()
            logger.info("  Redis pub/sub unsubscribed")
            raise
        except Exception as _listener_err:
            logger.exception(
                f"  [DIAG] pubsub: listener crashed — events will no longer "
                f"reach browser: {_listener_err}"
            )
            raise

    # ── Task 3: Audio receive + agent loop ────────────────────────────────────
    async def audio_loop():
        logger.info("  [DIAG] audio_loop: waiting for pubsub subscription confirmation…")
        try:
            await asyncio.wait_for(_subscribed.wait(), timeout=5.0)
            logger.info("  [DIAG] audio_loop: pubsub ready — proceeding")
        except asyncio.TimeoutError:
            logger.error(
                "  [DIAG] audio_loop: TIMEOUT waiting for pubsub SUBSCRIBE confirmation "
                "(>5s) — Redis may be unreachable or the listener task crashed"
            )

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
                    logger.info(
                        f"  ← PCM chunks received: {_chunk_count}, "
                        f"last chunk: {len(message)} bytes"
                    )

                is_speaking, utterance_bytes = vad.process_chunk(message)

                if is_speaking and not _speaking_logged:
                    logger.info("  VAD: speech detected — listening")
                    _speaking_logged = True
                    send_json({"type": "state", "state": "listening"})
                elif is_speaking:
                    send_json({"type": "state", "state": "listening"})
                elif not is_speaking and _speaking_logged:
                    pass

                if utterance_bytes is None:
                    continue

                _speaking_logged = False
                logger.info(f"  VAD: utterance complete — {len(utterance_bytes)} bytes")

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

                session_data = await session_manager.get(kiosk_id, session_uuid) or {}

                deps = RoboDeps(
                    kiosk_id=kiosk_id,
                    session_uuid=session_uuid,
                    visitor_name=session_data.get("visitor_name"),
                    current_appointment_id=session_data.get("current_appointment_id"),
                    host_id=session_data.get("host_id"),
                    checkin_stage=session_data.get("checkin_stage", "idle"),
                    redis=redis,
                )
                conversation_history_raw = session_data.get("conversation_history", "[]")
                if isinstance(conversation_history_raw, str) and conversation_history_raw:
                    conversation_history = ModelMessagesTypeAdapter.validate_json(
                        conversation_history_raw
                    )
                else:
                    conversation_history = []

                response_text, agent_result = await run_agent(
                    transcript, deps, conversation_history
                )
                t_agent_done = time.time()

                history_json: str = (
                    agent_result.all_messages_json().decode("utf-8")
                    if agent_result else "[]"
                )
                await session_manager.update(kiosk_id, session_uuid, {
                    "conversation_history": history_json,
                })

                send_json({"type": "response", "text": response_text})

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
    listener_task = asyncio.create_task(redis_listener())
    logger.info(
        f"  [DIAG] tasks created: writer={writer_task!r} listener={listener_task!r}"
    )
    try:
        await audio_loop()
    except WebSocketDisconnect:
        logger.info(f"✓ WebSocket disconnected: kiosk={kiosk_id}")
    except Exception as e:
        logger.exception(f"✗ WebSocket error: {e}")
    finally:
        listener_task.cancel()
        _send_queue.put_nowait(_STOP)
        await asyncio.gather(writer_task, listener_task, return_exceptions=True)
