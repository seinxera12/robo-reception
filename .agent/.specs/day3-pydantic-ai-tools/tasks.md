# Day 3 — Tasks: PydanticAI Agent + First 3 Tools

## Status Legend
- [ ] Not started
- [x] Complete
- [~] In progress
- [!] Blocked

---

## Task 1 — Add Dependencies

**Goal:** Add `pydantic-ai` and `groq` to the project and regenerate `requirements.txt`.

**Files touched:** `pyproject.toml`, `requirements.txt`

**Steps:**
- [x] Run `uv add pydantic-ai groq` inside the project virtualenv
- [x] Run `uv export --no-dev --format requirements-txt > requirements.txt` to regenerate

**Notes:**
- `pydantic-ai==1.107.0` — the `[groq]` extra doesn't exist in 1.x; `groq` is installed separately
- Both packages were already present; `requirements.txt` regenerated

---

## Task 2 — Agent Models (`app/agent/models.py`)

**Goal:** Define all Pydantic models for tool inputs/outputs and the `RoboDeps` dependency carrier.

**Files touched:** `app/agent/models.py` *(new)*

- [x] `AppointmentMatch` — output of `lookup_appointment`
- [x] `AvailabilitySlot` — single slot entry
- [x] `AvailabilityResult` — output of `check_availability`
- [x] `InfoResult` — output of `get_info`
- [x] `RoboDeps` — with `arbitrary_types_allowed = True`

---

## Task 3 — System Prompt (`app/agent/prompts.py`)

**Goal:** Create the system prompt function that injects current timestamp and kiosk ID on every agent run.

**Files touched:** `app/agent/prompts.py` *(new)*

- [x] `build_system_prompt(ctx) -> str` — pulls `ctx.deps.kiosk_id`, falls back to `"unknown"` if ctx is None
- [x] Injects `datetime.now(timezone.utc)` formatted string
- [x] Kept under 400 tokens

---

## Task 4 — Agent Core (`app/agent/core.py`)

**Goal:** Instantiate the PydanticAI `Agent` with Groq model and expose `run_agent()`.

**Files touched:** `app/agent/core.py` *(new)*

- [x] `_get_model()` returns `GroqModel("meta-llama/llama-4-scout-17b-16e-instruct", provider=GroqProvider(api_key=...))`
  - Uses `settings.groq_api_key or "placeholder-..."` so the agent instantiates even without a key set
- [x] `agent = Agent(...)` with `@agent.system_prompt` decorator (1.x API — callable via decorator, not constructor arg)
- [x] `run_agent(utterance, deps, conversation_history) -> str`
- [x] `_register_tools()` at module bottom

**Notes:**
- pydantic-ai 1.x: `system_prompt=callable` in constructor raises `TypeError: 'function' object is not iterable` — use `@agent.system_prompt` decorator instead
- `GroqProvider` must receive `api_key=` explicitly; env var is not auto-read unless configured externally

---

## Task 5 — Tool 1: `lookup_appointment` (`app/tools/appointments.py`)

**Goal:** Fuzzy name search and exact code search against `appointments` table using `pg_trgm`.

**Files touched:** `app/tools/appointments.py` *(new)*

- [x] `@agent.tool` decorated, `RunContext[RoboDeps]` first arg
- [x] Code path: exact match on `appointment_code.upper()` + status=scheduled + host join
- [x] Name path: pg_trgm `similarity() > 0.3` SQL threshold, Python accept threshold `>= 0.45`
- [x] Suggestions returned for `0.2 < score < 0.45`
- [x] `_appointment_to_match()` helper; calls `.value` on status enum

---

## Task 6 — Tool 2: `check_availability` (`app/tools/appointments.py` extended)

**Goal:** Find open `availability_slots` for a fuzzy-matched host on a given date.

**Files touched:** `app/tools/appointments.py` *(appended)*

- [x] `@agent.tool` with `host_name: str`, `date: str` params
- [x] Fuzzy host match: `similarity(name, :name) > 0.4`
- [x] Slot query filtered by `host_id` and `slot_start::date`
- [x] Open-slot filter done in Python, not SQL
- [x] `# TODO Day 4: cache` comment left in place

---

## Task 7 — Tool 3: `get_info` + FAQ data

**Goal:** Answer building FAQ questions from a local JSON file.

**Files touched:** `app/tools/info.py` *(new)*, `data/faq.json` *(new)*

- [x] `data/faq.json` with keys: `hours`, `parking`, `wifi`, `accessibility`, `cafeteria`, `security`
- [x] `_load_faq()` lazy-load guard, path resolved via `Path(__file__).parent.parent.parent`
- [x] Exact match → difflib fuzzy match (cutoff=0.5) → not-found fallback

---

## Task 8 — Wire Tools into Agent

**Goal:** Tool decorators run by importing tool modules after agent is defined.

**Files touched:** `app/agent/core.py` *(edit)*

- [x] `_register_tools()` at module bottom imports `app.tools.appointments` and `app.tools.info`
- [x] Verified: `agent._function_toolset.tools.keys()` == `['lookup_appointment', 'check_availability', 'get_info']`

---

## Task 9 — Update WebSocket Handler (`app/voice/ws_handler.py`)

**Goal:** Replace `HARDCODED_RESPONSE` with the real agent call.

**Files touched:** `app/voice/ws_handler.py` *(rewritten)*

- [x] Removed `HARDCODED_RESPONSE` constant
- [x] Added imports: `time`, `run_agent`, `RoboDeps`, `synthesise_stream`
- [x] `RoboDeps` built from session data per utterance
- [x] `run_agent(transcript, deps, conversation_history)` call inserted after STT
- [x] TTS replaced with `async for audio_chunk in synthesise_stream(response_text)`
- [x] LATENCY log: STT | Agent | TTS first byte | Total E2E

---

## Task 10 — Update Lifespan (`app/main.py`)

**Goal:** Validate Groq API key on startup and trigger tool registration at boot.

**Files touched:** `app/main.py` *(edit)*

- [x] GROQ_API_KEY presence check with warning if missing
- [x] `from app.agent.core import agent` imported in lifespan — surfaces tool registration errors at startup
- [x] Tool names logged on startup

---

## Task 11 — Update Health Endpoint (`app/api/health.py`)

**Goal:** Replace `"llm": "pending"` with a real Groq connectivity check.

**Files touched:** `app/api/health.py` *(edit)*

- [x] `AsyncGroq.models.list()` ping — `"ok"` / `"no_key"` / `"error: ..."`
- [x] `llm` included in `all_ready` evaluation
- [x] Added `from app.config import settings` import

---

## Task 12 — End-to-End Verification

**Goal:** Confirm all done criteria from the plan are met before marking Day 3 complete.

- [x] `from app.agent.core import agent` — no errors
- [x] Tool list: `['lookup_appointment', 'check_availability', 'get_info']`
- [x] All module imports clean (ws_handler, health, agent, tools)
- [x] `data/faq.json` readable with correct 6 keys
- [ ] FAQ live test: `"What are the office hours?"` → needs GROQ_API_KEY + running server
- [ ] Name lookup live test: `"I'm here to see Marcus"` → needs GROQ_API_KEY + DB
- [ ] Availability live test: `"Is Priya available tomorrow?"` → needs GROQ_API_KEY + DB
- [ ] Low confidence test: `"John Smyth"` → asks for clarification
- [ ] LATENCY log: Total E2E < 3.5s FAQ, < 4s DB queries
- [ ] `/health` returns `"llm": "ok"` — needs GROQ_API_KEY set in `.env`

---

## Dependency Map

```
Task 1 (deps)
    └─► Task 2 (models)
            └─► Task 3 (prompts)
                    └─► Task 4 (core — agent object)
                                ├─► Task 5 (tool: lookup_appointment)
                                ├─► Task 6 (tool: check_availability)
                                └─► Task 7 (tool: get_info + faq.json)
                                        └─► Task 8 (wire tools into agent)
                                                ├─► Task 9 (ws_handler)
                                                ├─► Task 10 (main.py lifespan)
                                                └─► Task 11 (health endpoint)
                                                        └─► Task 12 (verify — needs live env)
```
