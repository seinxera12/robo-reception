Reiteration of Understanding Before Day 4
What's Done So Far
Day 1: Infrastructure. Docker Compose, SQLAlchemy models, Alembic migrations with pg_trgm, pydantic-settings config, idempotent seed data, /health endpoint. Key lesson: async_sessionmaker must be called, not used directly as context manager.
Day 2: Voice pipeline. Lazy ML model imports inside load functions (not module level). asyncio.to_thread for CPU-bound model loading. VADProcessor as stateful per-connection class. Sentence-by-sentence TTS streaming. WebSocket handler orchestrating the full loop. AudioWorklet frontend. HF_HUB_OFFLINE=1 to prevent Kokoro HuggingFace network calls at runtime.
Day 3: PydanticAI agent replacing hardcoded response. @agent.tool decorator pattern with lazy module imports for registration. RunContext[RoboDeps] carrying deps into tools. AsyncSessionLocal() opened directly inside tools (no FastAPI DI). Three tools working: lookup_appointment (pg_trgm fuzzy, 0.3 SQL threshold / 0.45 Python threshold), check_availability (host fuzzy match + slot query), get_info (faq.json, difflib fuzzy, zero DB calls). Conversation history passed via message_history parameter.
What Day 3 Left Incomplete

check_availability has a Redis cache comment stub — redis was noted as "add to deps on Day 4"
Conversation history stored in session but not updated with result.all_messages() after each run — noted as "Day 4"
No write tools yet — agent can look up but can't check in, notify, or acknowledge

What Day 4 Must Deliver
Day 3 gave the agent eyes — it can read data. Day 4 gives it hands — it can write state, send notifications, and complete the full check-in loop. The single most important demo moment is: visitor checks in → host gets push notification on phone → host taps link → browser UI updates in real time. That full round-trip must work by end of today.
Four things to build: update_checkin_status, notify_host, list_hosts, the /acknowledge/{appointment_id} endpoint, and the Redis pub/sub broadcast that closes the loop back to the WebSocket.

Day 4 — Remaining Tools + Notification Round-Trip
What You're Actually Proving Today

Can the agent write a check-in to PostgreSQL and the data persists correctly?
Does notify_host send a real push to a phone via ntfy and does the link in the notification work?
When the host taps acknowledge, does the browser UI update within 3 seconds without polling?
Does the agent speak the right confirmation at each stage?


Mental Model: The Notification Round-Trip
The full loop has four actors and must be understood before writing any code:
[Kiosk Browser]                [FastAPI]              [Redis]         [Host Phone]
      |                            |                     |                  |
      | speak "check me in"        |                     |                  |
      |─────────────────────────→  |                     |                  |
      |                            | update_checkin_status (PostgreSQL)      |
      |                            | notify_host → ntfy HTTP POST            |
      |                            |                     |         push arrives
      |                            |                     |                  |
      |   state: "Host notified"   |                     |         tap link |
      |←────────────────────────── |                     |                  |
      |                            | GET /acknowledge/{id}                   |
      |                            |─────────────────────────────────────────|
      |                            | UPDATE appointments SET acknowledged=true
      |                            | PUBLISH Redis event ──→ |               |
      |                            |                     |                  |
      | ←── WebSocket push ────────|←── Redis subscribe ─|                  |
      | UI: "Host on their way" ✓  |                     |                  |
Two things make this work:

ntfy delivers the push to the host's phone with an embedded acknowledge URL
Redis pub/sub broadcasts the acknowledgement back to the kiosk WebSocket without polling

The WebSocket handler needs to listen to Redis while simultaneously receiving audio chunks. This requires running two async tasks concurrently — a pattern you'll implement today.

Step 1 — Tool 4: update_checkin_status (app/tools/appointments.py extended)
python# app/tools/appointments.py — add below existing tools

from datetime import datetime, timezone
from app.db.models import AppointmentStatus


class CheckinResult(BaseModel):
    success: bool
    appointment_id: str | None = None
    message: str = ""


@agent.tool
async def update_checkin_status(
    ctx: RunContext[RoboDeps],
    appointment_id: str,
) -> CheckinResult:
    """
    Mark a visitor as checked in. Call this after lookup_appointment succeeds
    and the visitor has confirmed their details.
    Sets status to checked_in and records the check-in timestamp.
    """
    logger.info(f"Tool: update_checkin_status(appointment_id={appointment_id})")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appt = result.scalar_one_or_none()

        if not appt:
            return CheckinResult(
                success=False,
                message=f"Appointment {appointment_id} not found."
            )

        if appt.status == AppointmentStatus.checked_in:
            return CheckinResult(
                success=True,
                appointment_id=appointment_id,
                message="Visitor was already checked in."
            )

        appt.status = AppointmentStatus.checked_in
        appt.check_in_at = datetime.now(timezone.utc)
        await session.commit()

        logger.info(f"✓ Checked in: appointment {appointment_id}")
        return CheckinResult(
            success=True,
            appointment_id=appointment_id,
            message="Visitor successfully checked in."
        )
Why no Redis cache invalidation here? The spec is explicit: appointment records are never cached. No cache to invalidate. The write goes straight to PostgreSQL and that's the only source of truth.

Step 2 — Tool 5: notify_host (app/tools/notifications.py)
python# app/tools/notifications.py
import logging
import httpx
from pydantic import BaseModel
from pydantic_ai import RunContext
from sqlalchemy import select

from app.agent.core import agent
from app.agent.models import RoboDeps
from app.config import settings
from app.db.models import Appointment, Host
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class NotifyResult(BaseModel):
    sent: bool
    channel: str | None = None
    message: str = ""


@agent.tool
async def notify_host(
    ctx: RunContext[RoboDeps],
    host_id: str,
    visitor_name: str,
    appointment_id: str,
) -> NotifyResult:
    """
    Send a push notification to the host via ntfy.
    The notification includes an acknowledgement link.
    Call this after update_checkin_status succeeds.
    """
    logger.info(f"Tool: notify_host(host_id={host_id}, visitor={visitor_name})")

    async with AsyncSessionLocal() as session:
        # Get host details
        result = await session.execute(
            select(Host).where(Host.id == host_id)
        )
        host = result.scalar_one_or_none()

        if not host:
            return NotifyResult(sent=False, message=f"Host {host_id} not found.")

        # Build acknowledge URL — must be reachable from host's phone
        # Use ngrok URL in dev (set BASE_URL in .env)
        ack_url = f"{settings.base_url}/acknowledge/{appointment_id}"
        topic = host.notification_channel

        # Build ntfy message
        ntfy_url = f"{settings.ntfy_host}/{topic}"
        payload = {
            "topic": topic,
            "title": f"Visitor arrived: {visitor_name}",
            "message": f"{visitor_name} is at reception for you.",
            "actions": [
                {
                    "action": "view",
                    "label": "I'm on my way ✓",
                    "url": ack_url,
                    "clear": True,
                }
            ],
            "priority": "high",
            "tags": ["bell", "office"],
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(ntfy_url, json=payload)
                response.raise_for_status()

            # Mark notification sent in DB
            appt_result = await session.execute(
                select(Appointment).where(Appointment.id == appointment_id)
            )
            appt = appt_result.scalar_one_or_none()
            if appt:
                appt.notification_sent = True
                await session.commit()

            logger.info(f"✓ Notification sent to {host.name} via {topic}")
            return NotifyResult(
                sent=True,
                channel=topic,
                message=f"Notification sent to {host.name}."
            )

        except httpx.HTTPError as e:
            logger.error(f"ntfy send failed: {e}")
            return NotifyResult(
                sent=False,
                message=f"Failed to notify host: {e}"
            )
Why httpx.AsyncClient instead of Apprise here? Apprise works well but ntfy's action buttons (the "I'm on my way" tap target) require sending a JSON payload with an actions array — Apprise abstracts this away and loses the action button. Direct httpx gives you full control over the ntfy payload. Apprise is better suited for multi-channel fan-out which you don't need here.

Step 3 — Tool 6: list_hosts (app/tools/hosts.py)
python# app/tools/hosts.py
import logging
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from pydantic_ai import RunContext
from sqlalchemy import text

from app.agent.core import agent
from app.agent.models import RoboDeps
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class HostInfo(BaseModel):
    host_id: str
    name: str
    department: str
    next_available_slot: str | None = None


class HostListResult(BaseModel):
    found: bool
    hosts: list[HostInfo] = []
    message: str = ""


@agent.tool
async def list_hosts(
    ctx: RunContext[RoboDeps],
    department: str | None = None,
) -> HostListResult:
    """
    List active staff members, optionally filtered by department.
    Returns each host with their next available slot today or tomorrow.
    Use this for walk-in visitors who don't have an appointment.
    """
    logger.info(f"Tool: list_hosts(department={department})")

    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        lookahead = now + timedelta(hours=48)

        if department:
            # Fuzzy match department name
            query = text("""
                SELECT
                    h.id, h.name, h.department,
                    MIN(s.slot_start) as next_slot
                FROM hosts h
                LEFT JOIN availability_slots s
                    ON s.host_id = h.id
                    AND s.slot_start >= :now
                    AND s.slot_start <= :lookahead
                    AND s.is_booked = false
                WHERE h.is_active = true
                  AND similarity(h.department, :dept) > 0.4
                GROUP BY h.id, h.name, h.department
                ORDER BY h.name
            """)
            result = await session.execute(
                query, {"dept": department, "now": now, "lookahead": lookahead}
            )
        else:
            query = text("""
                SELECT
                    h.id, h.name, h.department,
                    MIN(s.slot_start) as next_slot
                FROM hosts h
                LEFT JOIN availability_slots s
                    ON s.host_id = h.id
                    AND s.slot_start >= :now
                    AND s.slot_start <= :lookahead
                    AND s.is_booked = false
                WHERE h.is_active = true
                GROUP BY h.id, h.name, h.department
                ORDER BY h.department, h.name
            """)
            result = await session.execute(
                query, {"now": now, "lookahead": lookahead}
            )

        rows = result.fetchall()

        if not rows:
            return HostListResult(
                found=False,
                message=f"No active hosts found{' in ' + department if department else ''}."
            )

        hosts = [
            HostInfo(
                host_id=str(row.id),
                name=row.name,
                department=row.department,
                next_available_slot=row.next_slot.isoformat() if row.next_slot else None,
            )
            for row in rows
        ]

        logger.info(f"list_hosts: {len(hosts)} hosts found")
        return HostListResult(found=True, hosts=hosts)

Step 4 — /acknowledge/{appointment_id} Endpoint (app/api/acknowledge.py)
This endpoint is what the host taps on their phone. It must be publicly reachable — use ngrok in dev:
python# app/api/acknowledge.py
import logging
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.db.models import Appointment, Host
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/acknowledge/{appointment_id}", response_class=HTMLResponse)
async def acknowledge(appointment_id: str, request: Request):
    """
    Host taps this link from ntfy notification.
    Sets notification_acknowledged = true and broadcasts Redis event.
    """
    logger.info(f"Acknowledge request: appointment_id={appointment_id}")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Appointment, Host)
            .join(Host, Appointment.host_id == Host.id)
            .where(Appointment.id == appointment_id)
        )
        row = result.first()

        if not row:
            return HTMLResponse(
                content="<h2>Appointment not found.</h2>",
                status_code=404
            )

        appt, host = row

        if not appt.notification_acknowledged:
            appt.notification_acknowledged = True
            await session.commit()
            logger.info(f"✓ Acknowledged: {appt.visitor_name} → {host.name}")

        # Publish Redis event for WebSocket broadcast
        redis = request.app.state.redis
        import json
        event = json.dumps({
            "type": "host_acknowledged",
            "appointment_id": appointment_id,
            "visitor_name": appt.visitor_name,
            "host_name": host.name,
        })
        await redis.publish("robo:events", event)
        logger.info(f"Redis event published: host_acknowledged for {appointment_id}")

        # Return a friendly HTML page the host sees
        return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Acknowledged</title>
    <style>
        body {{
            font-family: -apple-system, sans-serif;
            display: flex; align-items: center; justify-content: center;
            min-height: 100vh; margin: 0; background: #f0fdf4;
        }}
        .card {{
            text-align: center; padding: 2rem;
            background: white; border-radius: 1rem;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            max-width: 320px;
        }}
        .check {{ font-size: 4rem; }}
        h2 {{ color: #16a34a; }}
        p {{ color: #6b7280; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="check">✓</div>
        <h2>On my way!</h2>
        <p>{host.name} is heading to reception to meet {appt.visitor_name}.</p>
    </div>
</body>
</html>
        """)

Step 5 — Redis Pub/Sub in WebSocket Handler
This is the most architecturally interesting part of Day 4. The WebSocket handler needs to simultaneously:

Receive audio chunks from the browser
Listen for Redis pub/sub events (host acknowledgements)

Python async handles this with asyncio.create_task — two concurrent tasks sharing one WebSocket connection:
python# app/voice/ws_handler.py — full updated version

import asyncio
import json
import logging
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agent.core import run_agent
from app.agent.models import RoboDeps
from app.config import settings
from app.voice.vad import VADProcessor
from app.voice.stt import transcribe
from app.voice.tts import synthesise_stream
from app.session.manager import SessionManager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/voice/{kiosk_id}")
async def voice_endpoint(websocket: WebSocket, kiosk_id: str):
    await websocket.accept()
    logger.info(f"✓ WebSocket accepted: kiosk={kiosk_id}")

    redis = websocket.app.state.redis
    session_manager = SessionManager(redis)
    session_uuid = await session_manager.create(kiosk_id)
    vad = VADProcessor()

    async def send_json(payload: dict):
        await websocket.send_text(json.dumps(payload))

    async def send_state(state: str):
        await send_json({"type": "state", "state": state})
        logger.info(f"→ State: {state}")

    # ── Task 1: Redis pub/sub listener ────────────────────────────────────
    async def redis_listener():
        """
        Listen for Redis events (e.g. host_acknowledged) and
        push them to the browser over the WebSocket.
        Runs concurrently with the audio receive loop.
        """
        pubsub = redis.pubsub()
        await pubsub.subscribe("robo:events")
        logger.info("Redis pub/sub subscribed: robo:events")

        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                event = json.loads(message["data"])
                logger.info(f"Redis event received: {event['type']}")

                if event["type"] == "host_acknowledged":
                    # Push UI update to browser
                    await send_json({
                        "type": "ui_update",
                        "event": "host_acknowledged",
                        "host_name": event["host_name"],
                        "visitor_name": event["visitor_name"],
                        "appointment_id": event["appointment_id"],
                    })
                    logger.info(f"✓ Host acknowledged event sent to browser")

        except asyncio.CancelledError:
            await pubsub.unsubscribe("robo:events")
            logger.info("Redis pub/sub unsubscribed")

    # ── Task 2: Audio receive + agent loop ────────────────────────────────
    async def audio_loop():
        chunk_count = 0
        speech_chunk_count = 0

        await send_state("idle")

        async for message in websocket.iter_bytes():
            chunk_count += 1
            if chunk_count % 100 == 0:
                logger.info(f"Chunks received: {chunk_count}")

            is_speaking, utterance_bytes = vad.process_chunk(message)

            if is_speaking:
                speech_chunk_count += 1
                if speech_chunk_count == 1:
                    logger.info("VAD: speech detected")
                await send_state("listening")

            if utterance_bytes is None:
                continue

            # Utterance complete
            logger.info(f"VAD: utterance complete — {len(utterance_bytes)} bytes")
            await send_state("thinking")
            t_utterance_end = time.time()

            transcript = await transcribe(utterance_bytes)
            t_stt_done = time.time()
            logger.info(f"STT ({t_stt_done - t_utterance_end:.2f}s): '{transcript}'")

            if not transcript.strip():
                await send_state("idle")
                speech_chunk_count = 0
                continue

            await send_json({"type": "transcript", "text": transcript})

            # Agent
            session_data = await session_manager.get(kiosk_id, session_uuid) or {}
            deps = RoboDeps(
                kiosk_id=kiosk_id,
                session_uuid=session_uuid,
                visitor_name=session_data.get("visitor_name"),
                current_appointment_id=session_data.get("current_appointment_id"),
            )
            history = session_data.get("conversation_history", [])

            response_text = await run_agent(transcript, deps, history)
            t_agent_done = time.time()
            logger.info(f"Agent ({t_agent_done - t_stt_done:.2f}s): '{response_text[:80]}'")

            await send_json({"type": "response", "text": response_text})
            await send_state("speaking")

            first_chunk = True
            async for audio_chunk in synthesise_stream(response_text):
                if first_chunk:
                    t_tts = time.time()
                    logger.info(
                        f"LATENCY — STT: {t_stt_done - t_utterance_end:.2f}s | "
                        f"Agent: {t_agent_done - t_stt_done:.2f}s | "
                        f"TTS: {t_tts - t_agent_done:.2f}s | "
                        f"Total: {t_tts - t_utterance_end:.2f}s"
                    )
                    first_chunk = False
                await websocket.send_bytes(audio_chunk)

            await send_json({"type": "audio_end"})
            await send_state("idle")
            speech_chunk_count = 0

    # ── Run both tasks concurrently ───────────────────────────────────────
    listener_task = asyncio.create_task(redis_listener())
    try:
        await audio_loop()
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: kiosk={kiosk_id}")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
    finally:
        listener_task.cancel()
        await asyncio.gather(listener_task, return_exceptions=True)
        await session_manager.delete(kiosk_id, session_uuid)
        logger.info(f"Session cleaned up: {session_uuid}")
Why create_task not gather? gather waits for both tasks to finish. You want the audio loop to be the "main" task and the Redis listener to be a background task that gets cancelled when the WebSocket disconnects. create_task + finally: listener_task.cancel() is the correct pattern.

Step 6 — Update Frontend for ui_update Events
The browser needs to handle the new ui_update event type and show the status badges:
html<!-- Add to index.html — status badges section -->
<div id="badges" style="margin-top: 1rem;">
    <span id="badge-checkin"  class="badge">☐ Checked In</span>
    <span id="badge-notified" class="badge">☐ Host Notified</span>
    <span id="badge-ack"      class="badge">☐ Host On Their Way</span>
</div>

<style>
.badge {
    display: inline-block;
    padding: 0.3rem 0.8rem;
    margin: 0.2rem;
    border-radius: 1rem;
    background: #333;
    color: #888;
    font-size: 0.9rem;
    transition: all 0.3s;
}
.badge.active {
    background: #16a34a;
    color: white;
}
</style>
Add to handleControl in your JS:
javascriptfunction handleControl(msg) {
    if (msg.type === "state") {
        statusEl.textContent = `State: ${msg.state}`;
    } else if (msg.type === "transcript") {
        transcriptEl.textContent = `You: ${msg.text}`;
    } else if (msg.type === "response") {
        responseEl.textContent = `Robo: ${msg.text}`;
    } else if (msg.type === "ui_update") {
        if (msg.event === "host_acknowledged") {
            document.getElementById("badge-ack").classList.add("active");
            responseEl.textContent = `${msg.host_name} is on their way to meet you.`;
            console.log("Host acknowledged:", msg);
        }
    } else if (msg.type === "audio_end") {
        // audio queue drains naturally
    }
}

// Call these from agent response handling when you detect check-in/notify
function setBadge(id, active) {
    const el = document.getElementById(id);
    if (active) el.classList.add("active");
    else el.classList.remove("active");
}
Also add a reset function for demo resets:
javascriptfunction resetBadges() {
    ["badge-checkin", "badge-notified", "badge-ack"].forEach(id => {
        document.getElementById(id).classList.remove("active");
    });
}
The cleanest way to light up badge-checkin and badge-notified is for the WebSocket handler to send explicit ui_update events after each tool completes. Add these to the agent response handling in ws_handler.py — or alternatively parse the agent's response text for keywords. The explicit event approach is cleaner and more reliable. Add to the tools:
python# After update_checkin_status succeeds in ws_handler context,
# send a ui_update. Best done by adding event publishing
# directly in the tool or by checking result in ws_handler.

# Simplest for Day 4 — publish from the tool itself:
# In update_checkin_status, after commit:
# await redis.publish("robo:events", json.dumps({
#     "type": "checkin_complete",
#     "appointment_id": appointment_id,
# }))
But tools don't have direct Redis access in the current design. The cleaner approach is to add Redis to RoboDeps:
python# app/agent/models.py — update RoboDeps
from typing import Any

class RoboDeps(BaseModel):
    kiosk_id: str
    session_uuid: str
    visitor_name: str | None = None
    current_appointment_id: str | None = None
    redis: Any = None   # injected from ws_handler

    model_config = {"arbitrary_types_allowed": True}
Then in ws_handler.py:
pythondeps = RoboDeps(
    kiosk_id=kiosk_id,
    session_uuid=session_uuid,
    visitor_name=session_data.get("visitor_name"),
    current_appointment_id=session_data.get("current_appointment_id"),
    redis=redis,   # ← pass redis client
)
And in tools that need to publish events:
python# notify_host — after sending notification:
if ctx.deps.redis:
    await ctx.deps.redis.publish("robo:events", json.dumps({
        "type": "notification_sent",
        "appointment_id": appointment_id,
        "host_name": host.name,
    }))

Step 7 — Register New Tools in core.py
python# app/agent/core.py — update _register_tools
def _register_tools():
    import app.tools.appointments   # lookup_appointment, check_availability, update_checkin_status
    import app.tools.info           # get_info
    import app.tools.notifications  # notify_host
    import app.tools.hosts          # list_hosts
    # Day 5: import app.tools.wayfinding

_register_tools()

Step 8 — Wire Acknowledge Router in main.py
python# main.py — add import and router
from app.api.acknowledge import router as acknowledge_router
app.include_router(acknowledge_router)

Step 9 — ngrok for Public Acknowledge URL
The host's phone needs to reach /acknowledge/{id}. On a local dev machine, use ngrok:
bash# In a separate terminal
ngrok http 8000
# Copy the https://xxxx.ngrok.io URL
Update .env:
bashBASE_URL=https://xxxx.ngrok.io
Restart the server — the acknowledge URL embedded in ntfy notifications will now be publicly reachable.

Verification Sequence
bash# 1. Confirm all tools register
uv run python -c "
from app.agent.core import agent
tools = list(agent._function_tools.keys())
print('Tools:', tools)
assert 'update_checkin_status' in tools
assert 'notify_host' in tools
assert 'list_hosts' in tools
print('All tools registered ✓')
"

# 2. Test acknowledge endpoint directly
curl -X GET localhost:8000/acknowledge/<any-appointment-id-from-seed>
# Should return HTML page and print Redis publish log

# 3. Test ntfy notification manually
curl -X POST http://localhost:8080/marcus-webb \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test notification",
    "message": "Sarah Chen is at reception",
    "actions": [{"action":"view","label":"On my way","url":"http://localhost:8000/acknowledge/test"}]
  }'
# Should appear in ntfy web UI at http://localhost:8080

# 4. Full Scenario 1 end-to-end via voice:
# Say: "Hi, I am Sarah Chen, I have a 2pm appointment with Marcus"
# Expected tool sequence in logs:
#   lookup_appointment(visitor_name="Sarah Chen") → found
#   update_checkin_status(appointment_id="...") → success
#   notify_host(host_id="...", visitor_name="Sarah Chen", ...) → sent
# Then tap acknowledge link from ntfy notification on phone
# Expected: browser UI shows badge-ack active within 3 seconds

# 5. Scenario 2 — walk-in
# Say: "I don't have an appointment, I'd like to see someone in Engineering"
# Expected: list_hosts(department="Engineering") → returns Marcus + Sarah Lim

Expected Terminal Output — Full Scenario 1
VAD: utterance complete — 31200 bytes
STT (1.02s): 'hi i am sarah chen i have a 2pm appointment with marcus'
Tool: lookup_appointment(visitor_name='sarah chen')
Appointment match: 'Sarah Chen' (confidence: 0.94)
Tool: update_checkin_status(appointment_id='abc-123')
✓ Checked in: appointment abc-123
Tool: notify_host(host_id='xyz-456', visitor='Sarah Chen')
✓ Notification sent to Marcus Webb via marcus-webb
Agent (2.14s): 'Welcome Sarah! You are checked in and Marcus has been notified. Head to Room 204 on Floor 2.'
LATENCY — STT: 1.02s | Agent: 2.14s | TTS: 0.39s | Total: 3.55s

[Host taps phone]
Redis event received: host_acknowledged
✓ Host acknowledged event sent to browser

What You're Learning Today
asyncio.create_task for concurrent async tasks — running the Redis listener alongside the audio loop without either blocking the other. This is a fundamental async pattern for any real-time system that handles multiple event sources.
Redis pub/sub — the difference between key-value storage (get/set) and pub/sub messaging (publish/subscribe). Pub/sub is push-based — subscribers receive messages the moment they're published, with no polling.
ntfy action buttons — the actions array in the JSON payload creates tappable buttons in the notification. The view action type opens a URL when tapped. This is what closes the round-trip loop.
Dependency injection into tools — passing Redis through RoboDeps so tools can publish events without global state. The arbitrary_types_allowed = True config on the Pydantic model is what allows non-Pydantic types (like the Redis client) to be carried in deps.
Tool sequencing by the LLM — the agent decides the order: lookup → checkin → notify. Your system prompt rules guide this but the LLM executes it. Watching the tool call sequence in logs tells you if the agent is reasoning correctly.

Day 4 Done Criteria
✓ All 6 tools registered — confirmed via agent._function_tools
✓ Scenario 1: voice check-in → checked_in in DB → ntfy push received on phone
✓ Acknowledge link in notification is reachable (ngrok active)
✓ Tapping acknowledge → browser badge updates within 3s (no refresh)
✓ Scenario 2: walk-in → list_hosts returns Engineering staff
✓ Redis pub/sub log shows publish + receive on acknowledge
✓ /health still returns all_ready: true
✓ DB shows notification_sent=true, notification_acknowledged=true after full loop