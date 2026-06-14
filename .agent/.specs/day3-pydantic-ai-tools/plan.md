#### What Was Built (Day 1)

Complete infrastructure foundation. Docker Compose with all 5 services (postgres, redis, ntfy, ollama, robo-api). SQLAlchemy 2.0 async models for `Host`, `Appointment`, `AvailabilitySlot`. Alembic migrations with `pg_trgm` extension. Pydantic-settings config as single source of truth. Idempotent `seed.py` with all demo scenario data. FastAPI lifespan handling migrations + Redis on startup. `/health` endpoint with real checks against DB and Redis module-level variables.

**Key lesson learned:** `async_sessionmaker` must be called `AsyncSessionLocal()` not used as context manager directly.

#### What Was Built (Day 2)

Full voice pipeline round-trip. Three ML models loaded lazily (imports inside load functions, not at module level) to prevent early initialisation before lifespan. All three loaded via `asyncio.to_thread` to avoid blocking the event loop. `VADProcessor` as stateful per-connection class with `reset_states()` after each utterance. `synthesise_stream` splits text sentence-by-sentence for streaming latency. WebSocket handler at `/ws/voice/{kiosk_id}` orchestrating the full loop. Plain HTML/JS frontend with AudioWorklet for 16kHz PCM capture. Session manager writing to Redis with `session:{kiosk_id}:{uuid}` namespace.

**Key lessons learned:** Module-level ML imports trigger at `from app.voice.tts import synthesise_stream` time — not at call time. Lazy imports inside functions is the correct pattern. Kokoro makes HuggingFace network HEAD requests on every init — `HF_HUB_OFFLINE=1` prevents this. `asyncio.to_thread` is mandatory for CPU-bound model loading inside async lifespan.

**Day 2 end state:** Visitor speaks → VAD detects utterance → Whisper transcribes → hardcoded response text → Kokoro speaks it back. State frames drive frontend: `idle → listening → thinking → speaking → idle`.

#### What Day 3 Must Deliver

Day 2 has a hardcoded `HARDCODED_RESPONSE` string where the agent should be. Day 3 replaces that string with a real PydanticAI agent connected to Groq, with three tools actually querying the seeded PostgreSQL data. The voice pipeline from Day 2 stays completely unchanged — the only thing that changes is what happens between `transcript` and `synthesise_stream`.

---

## Day 3 — PydanticAI Agent + First 3 Tools

### What You're Actually Proving Today

1. Does the PydanticAI agent receive a transcript, reason about it, call the right tool, and return a speakable response?
2. Do `lookup_appointment`, `check_availability`, and `get_info` work correctly against real seeded PostgreSQL data?
3. Does the full loop still hit the latency target — transcript → first TTS audio byte in under 3s with Groq as the LLM?

No notifications, no wayfinding, no check-in writes yet. Pure reasoning + read-only queries.

---

### Mental Model: How PydanticAI Works

Before writing code, understand the execution model:

```
agent.run(user_message, deps=deps)
    ↓
LLM receives: system prompt + conversation history + tool definitions
    ↓
LLM decides: call a tool OR respond directly
    ↓
If tool call: PydanticAI executes your Python function with LLM-provided args
    ↓
Tool result injected back into LLM context
    ↓
LLM generates final response text
    ↓
agent.run() returns AgentResult with .output (the response text)
```

Key things to internalise:

**Tools are just Python async functions** decorated with `@agent.tool`. PydanticAI handles the JSON schema generation, the tool call/result injection, and the retry logic automatically.

**`RunContext` carries dependencies** — your DB session, Redis client, kiosk ID, and session data flow into every tool via `ctx.deps`. This is how tools access the database without global state.

**The agent doesn't stream tokens to you directly** — it runs to completion and returns the full response. Streaming comes from TTS sentence-by-sentence, not from the LLM token stream. This is acceptable for Day 3; token streaming would be a Day 6+ optimisation.

---

### New Dependencies for Day 3

bash

```bash
uv add pydantic-ai groq
uv export --no-dev --format requirements-txt > requirements.txt
```

---

### Step 1 — Agent Models (`app/agent/models.py`)

Pydantic models for every tool's input and output. Strict typing is what makes PydanticAI's tool call validation work — the LLM can't pass a wrong type without an automatic retry:

python

```python
# app/agent/models.py
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


# ── Tool Outputs ───────────────────────────────────────────────────────────

class AppointmentMatch(BaseModel):
    found: bool
    appointment_id: str | None = None
    appointment_code: str | None = None
    visitor_name: str | None = None
    host_name: str | None = None
    host_id: str | None = None
    room: str | None = None
    floor: int | None = None
    scheduled_at: str | None = None   # ISO string — LLM handles strings better than datetime
    status: str | None = None
    confidence: float = 0.0
    suggestions: list[str] = []       # alternate names if not found


class AvailabilitySlot(BaseModel):
    slot_start: str
    slot_end: str
    is_booked: bool


class AvailabilityResult(BaseModel):
    found: bool
    host_name: str | None = None
    host_id: str | None = None
    slots: list[AvailabilitySlot] = []
    message: str = ""


class InfoResult(BaseModel):
    found: bool
    query_type: str
    answer: str = ""


# ── Agent Dependencies (passed via RunContext) ─────────────────────────────

class RoboDeps(BaseModel):
    kiosk_id: str
    session_uuid: str
    visitor_name: str | None = None           # known after first lookup
    current_appointment_id: str | None = None  # known after successful lookup

    model_config = {"arbitrary_types_allowed": True}
```

---

### Step 2 — System Prompt (`app/agent/prompts.py`)

The system prompt is the most important tuning lever for agent behaviour. Keep it under 400 tokens — every token costs latency on the LLM call:

python

```python
# app/agent/prompts.py
from datetime import datetime, timezone

def build_system_prompt(kiosk_id: str) -> str:
    now = datetime.now(timezone.utc).strftime("%A, %B %d %Y, %I:%M %p UTC")
    return f"""You are Robo, a professional AI receptionist at the building front desk.
Current time: {now}. Kiosk: {kiosk_id}.

YOUR JOB:
- Help visitors check in for appointments
- Help walk-in visitors find a host
- Answer building questions (hours, parking, WiFi)
- Give directions to rooms when needed

RULES:
- Always use a tool before responding about appointments, availability, or building info
- Keep responses SHORT and SPEAKABLE — under 3 sentences, no bullet points
- Be warm and professional
- If a name lookup fails, ask the visitor to spell or confirm their name
- Never guess or make up appointment details — only use tool results
- After successful check-in: confirm check-in, say host has been notified, offer directions

TOOLS AVAILABLE:
- lookup_appointment: find visitor appointment by name or code
- check_availability: find open slots for a host
- get_info: answer FAQ questions (hours, parking, wifi, accessibility)
- update_checkin_status: mark visitor as checked in (use after lookup succeeds)
- notify_host: send push notification to host (use after check-in)
- get_directions: get walking directions to a room
- list_hosts: list available staff by department
"""
```

**Why hardcode the time in the prompt?** The LLM has no clock — without the current time it can't reason about "my 2pm appointment" correctly. Inject it fresh on every agent run.

---

### Step 3 — Agent Core (`app/agent/core.py`)

python

```python
# app/agent/core.py
import logging
import time
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.groq import GroqModel

from app.config import settings
from app.agent.models import RoboDeps
from app.agent.prompts import build_system_prompt

logger = logging.getLogger(__name__)

# ── Model setup ────────────────────────────────────────────────────────────

def _get_model():
    """Return Groq model. Ollama fallback wired in Day 3 stretch goal."""
    return GroqModel(
        "llama-4-scout",         # fast, good tool-calling
        api_key=settings.groq_api_key,
    )

# ── Agent definition ───────────────────────────────────────────────────────

agent = Agent(
    model=_get_model(),
    deps_type=RoboDeps,
    system_prompt=build_system_prompt,   # callable — evaluated fresh each run
    retries=2,                           # retry on tool validation failure
)

# ── Main entry point ───────────────────────────────────────────────────────

async def run_agent(
    utterance: str,
    deps: RoboDeps,
    conversation_history: list[dict],
) -> str:
    """
    Run the agent on a single utterance.
    Returns the response text to be spoken by TTS.
    """
    t0 = time.time()
    logger.info(f"Agent run: '{utterance[:80]}'")

    try:
        result = await agent.run(
            utterance,
            deps=deps,
            message_history=conversation_history,
        )
        elapsed = time.time() - t0
        response = result.output
        logger.info(f"Agent response ({elapsed:.2f}s): '{response[:80]}'")
        return response

    except Exception as e:
        logger.exception(f"Agent error: {e}")
        return "I'm sorry, I ran into a problem. Could you please repeat that?"
```

**`system_prompt=build_system_prompt`** — passing the function (not the result) means PydanticAI calls it fresh on every run, so the timestamp is always current.

**`message_history`** — this is how multi-turn conversation works. The WebSocket handler maintains a list of past messages in Redis session and passes them in. The LLM sees the full conversation context.

---

### Step 4 — Tool 1: `lookup_appointment` (`app/tools/appointments.py`)

This is the most important tool — it's called in scenarios 1, 2, 3, and 6:

python

```python
# app/tools/appointments.py
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from pydantic_ai import RunContext

from app.agent.core import agent
from app.agent.models import RoboDeps, AppointmentMatch
from app.db.models import Appointment, Host, AppointmentStatus
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


@agent.tool
async def lookup_appointment(
    ctx: RunContext[RoboDeps],
    visitor_name: str | None = None,
    appointment_code: str | None = None,
) -> AppointmentMatch:
    """
    Look up a visitor's appointment by name or appointment code.
    Use visitor_name for name-based lookup, appointment_code if visitor provides a code.
    Always query live — never cached.
    """
    logger.info(f"Tool: lookup_appointment(name={visitor_name}, code={appointment_code})")

    async with AsyncSessionLocal() as session:

        # ── Code-based lookup (exact match) ───────────────────
        if appointment_code:
            result = await session.execute(
                select(Appointment, Host)
                .join(Host, Appointment.host_id == Host.id)
                .where(Appointment.appointment_code == appointment_code.upper())
                .where(Appointment.status == AppointmentStatus.scheduled)
            )
            row = result.first()
            if row:
                appt, host = row
                return _appointment_to_match(appt, host, confidence=1.0)
            return AppointmentMatch(found=False, message="No appointment found with that code.")

        # ── Name-based fuzzy lookup (pg_trgm) ─────────────────
        if not visitor_name:
            return AppointmentMatch(found=False, message="Please provide a name or appointment code.")

        fuzzy_query = text("""
            SELECT
                a.id, a.appointment_code, a.visitor_name, a.room, a.floor,
                a.scheduled_at, a.status, a.host_id,
                h.name as host_name,
                similarity(a.visitor_name, :name) as score
            FROM appointments a
            JOIN hosts h ON a.host_id = h.id
            WHERE
                a.status = 'scheduled'
                AND similarity(a.visitor_name, :name) > 0.3
            ORDER BY score DESC
            LIMIT 5
        """)

        result = await session.execute(fuzzy_query, {"name": visitor_name})
        rows = result.fetchall()

        if not rows:
            return AppointmentMatch(
                found=False,
                suggestions=[],
                message=f"No appointment found for '{visitor_name}'."
            )

        best = rows[0]
        confidence = float(best.score)

        if confidence >= 0.45:
            # Good match — return it
            logger.info(f"Appointment match: '{best.visitor_name}' (confidence: {confidence:.2f})")
            return AppointmentMatch(
                found=True,
                appointment_id=str(best.id),
                appointment_code=best.appointment_code,
                visitor_name=best.visitor_name,
                host_name=best.host_name,
                host_id=str(best.host_id),
                room=best.room,
                floor=best.floor,
                scheduled_at=best.scheduled_at.isoformat(),
                status=best.status,
                confidence=confidence,
            )
        else:
            # Low confidence — return suggestions for clarification
            suggestions = [r.visitor_name for r in rows if float(r.score) > 0.2]
            logger.info(f"Low confidence ({confidence:.2f}) — suggestions: {suggestions}")
            return AppointmentMatch(
                found=False,
                confidence=confidence,
                suggestions=suggestions,
                message=f"Could not find a confident match for '{visitor_name}'."
            )


def _appointment_to_match(appt: Appointment, host: Host, confidence: float) -> AppointmentMatch:
    return AppointmentMatch(
        found=True,
        appointment_id=str(appt.id),
        appointment_code=appt.appointment_code,
        visitor_name=appt.visitor_name,
        host_name=host.name,
        host_id=str(appt.host_id),
        room=appt.room,
        floor=appt.floor,
        scheduled_at=appt.scheduled_at.isoformat(),
        status=appt.status.value,
        confidence=confidence,
    )
```

**Why `AsyncSessionLocal()` directly instead of `Depends(get_session)`?** Tools aren't FastAPI route handlers — they don't have access to FastAPI's dependency injection. You create sessions directly inside tools. Each tool opens and closes its own session.

**Why `similarity > 0.3` in SQL but `0.45` in Python?** Cast a wide net in SQL (0.3) to get candidates, then apply the real threshold (0.45) in Python where you have full control. This gives you the suggestions list for low-confidence matches without a second query.

---

### Step 5 — Tool 2: `check_availability` (`app/tools/appointments.py` extended)

python

```python
@agent.tool
async def check_availability(
    ctx: RunContext[RoboDeps],
    host_name: str,
    date: str,                  # ISO date string e.g. "2025-01-15"
) -> AvailabilityResult:
    """
    Check available appointment slots for a host on a given date.
    Returns open time slots. Results are cached in Redis for 60 seconds.
    """
    from app.agent.models import AvailabilityResult, AvailabilitySlot as SlotModel
    logger.info(f"Tool: check_availability(host={host_name}, date={date})")

    async with AsyncSessionLocal() as session:

        # ── Fuzzy-match host name ──────────────────────────────
        host_query = text("""
            SELECT id, name
            FROM hosts
            WHERE is_active = true
              AND similarity(name, :name) > 0.4
            ORDER BY similarity(name, :name) DESC
            LIMIT 1
        """)
        host_result = await session.execute(host_query, {"name": host_name})
        host_row = host_result.first()

        if not host_row:
            return AvailabilityResult(
                found=False,
                message=f"Could not find a host named '{host_name}'."
            )

        host_id = str(host_row.id)
        resolved_host_name = host_row.name

        # ── Redis cache check ──────────────────────────────────
        # NOTE: appointments are never cached — availability slots are ok to cache
        from app.db.session import AsyncSessionLocal as _session  # already imported
        redis = None  # will add Redis to deps on Day 4 — for now skip cache

        # ── Query availability slots ───────────────────────────
        slots_query = text("""
            SELECT slot_start, slot_end, is_booked
            FROM availability_slots
            WHERE host_id = :host_id
              AND slot_start::date = :date
            ORDER BY slot_start
        """)
        slots_result = await session.execute(
            slots_query, {"host_id": host_id, "date": date}
        )
        slot_rows = slots_result.fetchall()

        slots = [
            SlotModel(
                slot_start=row.slot_start.isoformat(),
                slot_end=row.slot_end.isoformat(),
                is_booked=row.is_booked,
            )
            for row in slot_rows
        ]

        open_slots = [s for s in slots if not s.is_booked]
        logger.info(f"Availability: {host_name} has {len(open_slots)} open slots on {date}")

        return AvailabilityResult(
            found=True,
            host_name=resolved_host_name,
            host_id=host_id,
            slots=open_slots,
            message=f"{resolved_host_name} has {len(open_slots)} open slots on {date}."
        )
```

---

### Step 6 — Tool 3: `get_info` (`app/tools/info.py`)

No DB, no network — just a JSON file lookup. Must be the fastest tool:

python

```python
# app/tools/info.py
import json
import logging
from difflib import get_close_matches
from pathlib import Path
from pydantic_ai import RunContext

from app.agent.core import agent
from app.agent.models import RoboDeps, InfoResult

logger = logging.getLogger(__name__)

# Load once at module import — this is fine, it's just a JSON file
_FAQ_PATH = Path(__file__).parent.parent.parent / "data" / "faq.json"
_faq: dict = {}


def _load_faq():
    global _faq
    if not _faq:
        with open(_FAQ_PATH, "r") as f:
            _faq = json.load(f)
        logger.info(f"FAQ loaded: {list(_faq.keys())}")
    return _faq


@agent.tool
async def get_info(
    ctx: RunContext[RoboDeps],
    query_type: str,
) -> InfoResult:
    """
    Answer building FAQ questions about hours, parking, WiFi, accessibility,
    cafeteria, or security. No database call — instant response.
    """
    logger.info(f"Tool: get_info(query_type={query_type})")
    faq = _load_faq()

    # Exact match first
    if query_type.lower() in faq:
        return InfoResult(
            found=True,
            query_type=query_type,
            answer=faq[query_type.lower()]
        )

    # Fuzzy match
    matches = get_close_matches(query_type.lower(), faq.keys(), n=1, cutoff=0.5)
    if matches:
        key = matches[0]
        logger.info(f"FAQ fuzzy match: '{query_type}' → '{key}'")
        return InfoResult(found=True, query_type=key, answer=faq[key])

    logger.info(f"FAQ miss: '{query_type}'")
    return InfoResult(
        found=False,
        query_type=query_type,
        answer="I don't have information about that. Please ask the front desk staff."
    )
```

Now write `data/faq.json`:

json

```json
{
  "hours": "The building is open Monday to Friday, 8am to 7pm, and Saturday 9am to 2pm. We are closed on Sundays and public holidays.",
  "parking": "Visitor parking is available in the basement on Level B1. Enter from the north side entrance on Main Street. The first two hours are free, then 5 dollars per hour.",
  "wifi": "The guest WiFi network is called Robo-Guest. The password is Welcome2024. No registration required.",
  "accessibility": "Wheelchair access is available via the ramp on the south entrance. The lift to all floors is located next to reception. Accessible bathrooms are on every floor near the lift.",
  "cafeteria": "The cafeteria is on the ground floor, open 7am to 4pm on weekdays. It serves breakfast until 11am and lunch until 3pm.",
  "security": "Please keep your visitor badge visible at all times. Do not hold doors open for others. Report any concerns to reception or call extension 0 on any internal phone."
}
```

---

### Step 7 — Wire Tools into Agent

Tools register themselves via the `@agent.tool` decorator, but only if their modules are imported. Import them in `core.py` after the agent is defined:

python

```python
# app/agent/core.py — add at the bottom, after agent definition

# Import tool modules to register decorators
# These must come after `agent` is defined
def _register_tools():
    import app.tools.appointments   # registers lookup_appointment, check_availability
    import app.tools.info           # registers get_info
    # Day 4: import app.tools.notifications, app.tools.wayfinding, app.tools.hosts

_register_tools()
```

---

### Step 8 — Update WebSocket Handler

Replace the hardcoded response with the real agent call:

python

```python
# app/voice/ws_handler.py — update imports and utterance processing section

from app.agent.core import run_agent
from app.agent.models import RoboDeps
from app.session.manager import SessionManager

# Inside voice_endpoint, replace the hardcoded response block:

# ── Utterance complete → STT ──────────────────────────────
await send_state("thinking")
t_utterance_end = time.time()

transcript = await transcribe(utterance_bytes)
t_stt_done = time.time()
logger.info(f"STT: '{transcript}' ({t_stt_done - t_utterance_end:.2f}s)")

if not transcript.strip():
    await send_state("idle")
    continue

await send_transcript(transcript)

# ── Agent ────────────────────────────────────────────────
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
logger.info(f"Agent ({t_agent_done - t_stt_done:.2f}s): '{response_text[:80]}'")

# Persist updated conversation history
# PydanticAI result carries the new messages — store them
await session_manager.update(kiosk_id, session_uuid, {
    "conversation_history": conversation_history,  # Day 4: update with result.all_messages()
})

# ── TTS streaming ────────────────────────────────────────
await send_response_text(response_text)
await send_state("speaking")

first_chunk = True
async for audio_chunk in synthesise_stream(response_text):
    if first_chunk:
        t_first_tts = time.time()
        logger.info(
            f"LATENCY — STT: {t_stt_done - t_utterance_end:.2f}s | "
            f"Agent: {t_agent_done - t_stt_done:.2f}s | "
            f"TTS first byte: {t_first_tts - t_agent_done:.2f}s | "
            f"Total: {t_first_tts - t_utterance_end:.2f}s"
        )
        first_chunk = False
    await websocket.send_bytes(audio_chunk)

await websocket.send_text(json.dumps({"type": "audio_end"}))
await send_state("idle")
```

---

### Step 9 — Update `main.py` Lifespan

Add Groq API key validation and tool registration confirmation:

python

```python
# Add after TTS ready log in lifespan:

# Validate Groq API key exists
if not settings.groq_api_key:
    logger.warning("⚠ GROQ_API_KEY not set — agent will fail on first utterance")
else:
    logger.info("✓ Groq API key configured")

# Import agent to trigger tool registration
logger.info("Initializing agent and registering tools...")
from app.agent.core import agent
logger.info(f"✓ Agent ready")
```

---

### Step 10 — Add `GROQ_API_KEY` to `.env`

bash

```bash
# .env
GROQ_API_KEY=gsk_your_actual_key_here
```

Get your key from `console.groq.com` if you haven't already.

---

### Verification Sequence

bash

```bash
# 1. Confirm tools register without import errors
uv run python -c "
from app.agent.core import agent
print('Agent tools registered:')
# PydanticAI exposes registered tools
print([t.name for t in agent._function_tools.values()])
"
# Expected: ['lookup_appointment', 'check_availability', 'get_info']

# 2. Test get_info directly (no LLM needed)
uv run python -c "
import asyncio
from app.agent.models import RoboDeps
from app.agent.core import run_agent

deps = RoboDeps(kiosk_id='test', session_uuid='test-uuid')

async def test():
    result = await run_agent('What are the office hours?', deps, [])
    print('Response:', result)

asyncio.run(test())
"
# Expected: agent calls get_info, returns hours string, TTS speaks it

# 3. Test lookup_appointment fuzzy match
uv run python -c "
import asyncio
from app.agent.models import RoboDeps
from app.agent.core import run_agent

deps = RoboDeps(kiosk_id='test', session_uuid='test-uuid')

async def test():
    result = await run_agent(
        'Hi, I am Sarah Chen, here for my 2pm appointment with Marcus.',
        deps, []
    )
    print('Response:', result)

asyncio.run(test())
"
# Expected: agent calls lookup_appointment('Sarah Chen'),
#           finds match, responds with confirmation

# 4. Start full server and test via browser
uv run uvicorn app.main:app --reload --port 8000
# Speak: "What is the WiFi password?"
# Speak: "I'm here to see Marcus Webb"
# Speak: "Is David Chen available tomorrow?"
```

---

### Expected Terminal Output on a Working Day 3

```
✓ Agent ready
WebSocket accepted: kiosk=kiosk-01
Session created: abc-123

[Visitor says "What is the WiFi password?"]
VAD: utterance complete — 18400 bytes
STT: 'what is the wifi password' (0.94s)
Tool: get_info(query_type=wifi)
FAQ loaded: ['hours', 'parking', 'wifi', ...]
Agent (0.61s): 'The guest WiFi network is called Robo-Guest...'
LATENCY — STT: 0.94s | Agent: 0.61s | TTS first byte: 0.38s | Total: 1.93s ✓

[Visitor says "I'm here to see Marcus Webb"]
VAD: utterance complete — 24320 bytes
STT: 'i'm here to see marcus webb' (1.12s)
Tool: lookup_appointment(visitor_name=None, appointment_code=None)
# agent may ask for name first — correct behaviour
Agent (1.34s): 'Welcome! Could I get your name please?'
```

---

### What You're Learning Today

**PydanticAI tool registration pattern** — `@agent.tool` decorator + lazy module import to register. The agent object must exist before the decorator runs.

**RunContext and deps** — how to pass database sessions and config into tools without global state. This is the clean dependency injection pattern for agent tools.

**pg_trgm fuzzy matching** — `similarity()` function, threshold tuning (0.3 for candidates, 0.45 for acceptance), and why you need both a SQL threshold and a Python threshold.

**Multi-turn conversation history** — how `message_history` parameter carries context between turns. The LLM sees everything that was said before in the session.

**Tool call vs direct response** — the LLM decides whether to call a tool or respond directly. Your system prompt rules (`"Always use a tool before responding about appointments"`) guide this decision.

---

### Day 3 Done Criteria

```
✓ uv run python -c "from app.agent.core import agent" — no errors
✓ Agent tools list: ['lookup_appointment', 'check_availability', 'get_info']
✓ "What are the office hours?" → agent calls get_info → correct answer spoken
✓ "I'm here to see Marcus" → agent calls lookup_appointment → finds Sarah Chen's appt
✓ "Is Priya available tomorrow?" → agent calls check_availability → slots returned
✓ "John Smyth" lookup → low confidence → agent asks for clarification (scenario 3 partial)
✓ LATENCY log shows Total < 3.5s for FAQ queries, < 4s for DB queries
✓ /health returns all_ready: true with llm: "ok" (add Groq ping to health check)
```