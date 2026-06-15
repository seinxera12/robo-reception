# app/chat/http_handler.py
import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pydantic_ai.messages import ModelMessagesTypeAdapter

from app.agent.core import run_agent
from app.agent.models import RoboDeps
from app.config import settings
from app.session.manager import SessionManager

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────

class SessionInitResponse(BaseModel):
    session_uuid: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Non-empty user message")
    session_uuid: str


class ChatResponse(BaseModel):
    response: str


# ── Route 1: Session initialisation ──────────────────────────────────────

@router.post("/chat/{kiosk_id}/session", response_model=SessionInitResponse)
async def create_session(kiosk_id: str, request: Request) -> SessionInitResponse:
    """
    Create a new shared session for the given kiosk.
    Called once at page load; the returned session_uuid is used by both
    the chat HTTP endpoint and the voice WebSocket.
    """
    redis = request.app.state.redis
    session_manager = SessionManager(redis)
    session_uuid = await session_manager.create(kiosk_id)
    logger.info(f"Chat session created: kiosk={kiosk_id} session={session_uuid}")
    return SessionInitResponse(session_uuid=session_uuid)


# ── Route 2: Chat message ─────────────────────────────────────────────────

@router.post("/chat/{kiosk_id}", response_model=ChatResponse)
async def chat(kiosk_id: str, body: ChatRequest, request: Request) -> ChatResponse:
    """
    Accept a text message from the chat panel, run the agent, return the response.
    Shares session state with the voice WebSocket via session_uuid.
    """
    redis = request.app.state.redis
    session_manager = SessionManager(redis)

    # ── Load or create session ────────────────────────────────────────────
    session_data = await session_manager.get(kiosk_id, body.session_uuid)
    if session_data is None:
        # Session not found (expired or unknown UUID) — create a fresh one
        logger.warning(
            f"Chat: session not found for kiosk={kiosk_id} uuid={body.session_uuid!r} "
            f"— creating new session"
        )
        new_uuid = await session_manager.create(kiosk_id)
        session_data = await session_manager.get(kiosk_id, new_uuid) or {}
        session_uuid = new_uuid
    else:
        session_uuid = body.session_uuid

    # ── Deserialise conversation history ──────────────────────────────────
    conversation_history_raw = session_data.get("conversation_history", "[]")
    if isinstance(conversation_history_raw, str) and conversation_history_raw:
        try:
            conversation_history = ModelMessagesTypeAdapter.validate_json(
                conversation_history_raw
            )
        except Exception:
            conversation_history = []
    elif isinstance(conversation_history_raw, list):
        # Freshly created sessions store [] as a list, not a JSON string
        conversation_history = []
    else:
        conversation_history = []

    # ── Build agent dependencies ──────────────────────────────────────────
    deps = RoboDeps(
        kiosk_id=kiosk_id,
        session_uuid=session_uuid,
        visitor_name=session_data.get("visitor_name"),
        current_appointment_id=session_data.get("current_appointment_id"),
        host_id=session_data.get("host_id"),
        checkin_stage=session_data.get("checkin_stage", "idle"),
        redis=redis,
    )

    # ── Run agent (30-second timeout) ─────────────────────────────────────
    try:
        response_text, agent_result = await asyncio.wait_for(
            run_agent(body.message, deps, conversation_history),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.error(
            f"Chat: agent timed out for kiosk={kiosk_id} session={session_uuid!r}"
        )
        raise HTTPException(status_code=504, detail="Agent response timed out")

    # ── Persist updated conversation history ──────────────────────────────
    if agent_result is not None:
        history_json: str = agent_result.all_messages_json().decode("utf-8")
        try:
            await session_manager.update(kiosk_id, session_uuid, {
                "conversation_history": history_json,
            })
        except Exception as e:
            # Non-fatal — log and continue; the response is still useful
            logger.error(
                f"Chat: failed to persist history for session={session_uuid!r}: {e}"
            )
    else:
        logger.warning(
            f"Chat: agent_result is None for session={session_uuid!r} — "
            "history not persisted (agent error path)"
        )

    logger.info(
        f"Chat: kiosk={kiosk_id} session={session_uuid!r} "
        f"msg={body.message[:60]!r} → {response_text[:60]!r}"
    )
    return ChatResponse(response=response_text)


# ── Route 3: SSE badge-event stream ──────────────────────────────────────

@router.get("/chat/{kiosk_id}/events")
async def chat_events(
    kiosk_id: str,
    request: Request,
    session_uuid: str = Query(..., description="Session UUID to filter badge events for"),
):
    """
    Server-Sent Events stream that pushes Redis pub/sub badge events to the
    browser chat panel.  One persistent HTTP connection per page load.
    Events are filtered by session_uuid so multiple concurrent kiosk sessions
    receive only their own badge updates.
    """
    redis_app = request.app.state.redis

    async def event_generator():
        # Create a dedicated aioredis client with the pure-Python RESP2 parser.
        # hiredis has a known incompatibility with asyncio pubsub that causes
        # messages to be silently dropped — same mitigation as the voice handler.
        from redis.asyncio.connection import _AsyncRESP2Parser

        pubsub_redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            parser_class=_AsyncRESP2Parser,
            socket_keepalive=True,
        )
        pubsub = pubsub_redis.pubsub()
        await pubsub.subscribe("robo:events")
        logger.info(
            f"SSE: subscribed to robo:events "
            f"kiosk={kiosk_id} session={session_uuid!r}"
        )

        try:
            while True:
                # get_message() with a timeout so we can emit keepalive pings
                # and avoid blocking the event loop indefinitely.
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=20.0
                )

                if message is None:
                    # Keepalive ping — prevents proxy/browser from closing the
                    # idle connection.
                    yield 'data: {"type":"ping"}\n\n'
                    continue

                if message.get("type") != "message":
                    continue

                raw = message.get("data", "")
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError as e:
                    logger.warning(f"SSE: JSON decode failed: {e}  raw={raw!r}")
                    continue

                # Filter — only forward events that belong to this session
                if event.get("session_uuid") != session_uuid:
                    continue

                logger.info(
                    f"SSE: forwarding event type={event.get('type')!r} "
                    f"to session={session_uuid!r}"
                )
                yield f"data: {json.dumps(event)}\n\n"

        except asyncio.CancelledError:
            # Client disconnected (tab closed / navigation)
            logger.info(
                f"SSE: client disconnected "
                f"kiosk={kiosk_id} session={session_uuid!r}"
            )
        except Exception as e:
            logger.exception(
                f"SSE: generator crashed "
                f"kiosk={kiosk_id} session={session_uuid!r}: {e}"
            )
            yield f'data: {{"type":"error","message":"Stream error"}}\n\n'
        finally:
            try:
                await pubsub.unsubscribe("robo:events")
                await pubsub.aclose()
                await pubsub_redis.aclose()
                logger.info(
                    f"SSE: pub/sub cleaned up "
                    f"kiosk={kiosk_id} session={session_uuid!r}"
                )
            except Exception as cleanup_err:
                logger.warning(f"SSE: cleanup error: {cleanup_err}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering for SSE
        },
    )
