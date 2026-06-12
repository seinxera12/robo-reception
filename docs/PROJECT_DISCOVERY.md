# Robo Reception Assistant — Project Discovery

**Document Version:** 1.0  
**Generated:** June 12, 2026  
**Python Version:** 3.11  
**Status:** Active Development

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Project Purpose & Architecture](#project-purpose--architecture)
3. [Repository Structure](#repository-structure)
4. [Runtime Architecture](#runtime-architecture)
5. [Configuration & Environment](#configuration--environment)
6. [Dependency Analysis](#dependency-analysis)
7. [Database Architecture](#database-architecture)
8. [API Surface](#api-surface)
9. [Voice Processing Pipeline](#voice-processing-pipeline)
10. [Workflow Documentation](#workflow-documentation)
11. [Integration Mapping](#integration-mapping)
12. [Developer Workflow Guide](#developer-workflow-guide)
13. [Implemented Features](#implemented-features)
14. [Known Gaps & Work In Progress](#known-gaps--work-in-progress)
15. [End-to-End Request Flow](#end-to-end-request-flow)

---

## Executive Summary

### Project Name
**Robo Reception Assistant** (reception-robo)

### Purpose
Robo is a voice-enabled reception assistant kiosk system that automates visitor check-in via real-time voice conversation. The system listens to visitor inquiries, performs speech-to-text (STT) transcription, processes responses, and returns synthesized audio feedback.

### Problem Being Solved
- Manual reception workflows are time-consuming
- Visitors often wait without guidance
- Reception staff spend time on repetitive check-in tasks
- The system aims to streamline visitor check-in, appointment lookups, and host notifications

### High-Level Architecture

```
┌─ Frontend (Web Audio API) ──────────────────────────────────────┐
│  ├─ Mic input via AudioWorklet (16kHz, Int16 PCM)               │
│  └─ Speaker output via Web Audio playback                       │
│     
│     WebSocket bidirectional stream (binary + JSON)
│
├─ Backend (FastAPI + Python 3.11) ────────────────────────────────┤
│  ├─ Voice Pipeline:                                             │
│  │  ├─ VAD (Silero VAD via torch)                              │
│  │  ├─ STT (Faster-Whisper small.en model)                     │
│  │  ├─ Response Generation (hardcoded Day 2, LLM ready)        │
│  │  └─ TTS (Kokoro with streaming)                             │
│  │                                                              │
│  ├─ Session Management (Redis)                                 │
│  └─ API Layer (health checks, WebSocket routes)               │
│                                                                │
├─ Data Layer ──────────────────────────────────────────────────────┤
│  ├─ PostgreSQL (appointments, hosts, slots)                   │
│  └─ Redis (sessions, transient state)                         │
│                                                                │
└─ Supporting Services ───────────────────────────────────────────┘
   ├─ Ntfy (push notifications)
   ├─ Ollama (local LLM inference, future)
   └─ Docker Compose orchestration
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | HTML5, Web Audio API, AudioWorklet | Real-time voice capture & playback |
| **Backend** | FastAPI 0.136+, uvicorn | REST/WebSocket server |
| **STT** | Faster-Whisper 1.2.1 | Speech recognition (small.en model) |
| **TTS** | Kokoro 0.9.4 | Speech synthesis (af_heart voice) |
| **VAD** | Silero VAD (PyTorch) | Voice activity detection |
| **Database** | PostgreSQL 16 + SQLAlchemy 2.0 | Persistent storage (appointments, hosts) |
| **Session Store** | Redis 7 | In-memory session & transient state |
| **Async Runtime** | asyncio, asyncpg | Async/await concurrency |
| **Migrations** | Alembic 1.18+ | Schema version control |
| **Notifications** | Ntfy | Push notifications to hosts |
| **LLM** | Groq (groq-sdk) | Future: intelligent responses (configured, not yet used) |
| **Process Manager** | Docker Compose | Local development & container orchestration |

---

## Repository Structure

### Root-Level Organization

```
reception-robo/
├── app/                           # Main application package
│   ├── main.py                    # FastAPI app, lifespan, routes
│   ├── config.py                  # Pydantic settings (env vars)
│   ├── api/                       # REST/WebSocket endpoints
│   │   ├── health.py              # /health, /ping routes
│   │   └── __init__.py
│   ├── db/                        # Database & ORM
│   │   ├── models.py              # SQLAlchemy models (Host, Appointment, AvailabilitySlot)
│   │   ├── session.py             # AsyncSession factory, engine setup
│   │   ├── migrations/            # Alembic migrations
│   │   │   ├── versions/          # Migration scripts (4 files)
│   │   │   │   ├── 19f29f6b8ce2_initial_schema.py
│   │   │   │   ├── 50f89190b8fb_make_slot_timestamps_timezone_aware.py
│   │   │   │   ├── 5a0572bb674c_enable_pg_trgm.py
│   │   │   │   └── ea2e3884ce92_make_appointment_timestamps_timezone_.py
│   │   │   ├── env.py             # Alembic environment
│   │   │   └── script.py.mako     # Migration template
│   │   ├── base.py                # SQLAlchemy declarative base
│   │   └── __init__.py
│   ├── voice/                     # Voice processing pipeline
│   │   ├── stt.py                 # Speech-to-text (Faster-Whisper)
│   │   ├── tts.py                 # Text-to-speech (Kokoro)
│   │   ├── vad.py                 # Voice activity detection (Silero)
│   │   ├── ws_handler.py          # WebSocket handler, orchestrator
│   │   └── __init__.py
│   ├── session/                   # Session management
│   │   ├── manager.py             # Redis-backed session store
│   │   └── __init__.py
│   ├── agent/                     # (Empty, reserved for LLM agent)
│   │   └── __init__.py
│   ├── tools/                     # (Empty, reserved for tool calling)
│   │   └── __init__.py
│   ├── notifications/             # (Empty, reserved for notification handlers)
│   ├── wayfinding/                # (Empty, reserved for wayfinding logic)
│   └── __init__.py
├── frontend/                      # Browser client
│   ├── index.html                 # Test client with Web Audio API
│   └── worklet.js                 # AudioWorklet for low-latency mic capture
├── config/                        # Infrastructure config
│   └── ntfy/
│       └── server.yml             # Ntfy server configuration
├── data/                          # (Empty, reserved for data files)
├── tests/                         # (Empty, test suite TBD)
├── docs/                          # Documentation
├── docker-compose.yml             # Full stack orchestration
├── DockerFile                     # Container image spec
├── Makefile                       # Developer commands
├── alembic.ini                    # Alembic config (points to app/db/migrations)
├── pyproject.toml                 # Project metadata, dependencies
├── requirements.txt               # Frozen pip requirements (auto-generated by uv)
├── seed.py                        # Database seeder (4 hosts, 5 appointments)
├── main.py                        # Unused entry point (should be deleted or refactored)
├── .env.example                   # Environment variables template
├── .env                           # (Git-ignored, local secrets)
├── .gitignore                     # Standard Python ignore patterns
├── .python-version                # Python 3.11 specification
├── README.md                      # (Empty, minimal docs)
└── uv.lock                        # uv dependency lock file (replacement for pip-tools)
```

### Key Directory Responsibilities

| Directory | Purpose | Ownership | Status |
|-----------|---------|-----------|--------|
| `app/` | Core application logic | Backend team | Active |
| `app/voice/` | Real-time voice pipeline | Audio/ML team | Core functionality |
| `app/db/` | Data persistence layer | DB/Backend team | Active |
| `app/api/` | HTTP/WebSocket endpoints | Backend team | Minimal (health only) |
| `frontend/` | Web client | Frontend team | Minimal prototype |
| `tests/` | Test suite | QA/Backend team | **NOT STARTED** |
| `config/` | Infra configuration | DevOps team | Partial (ntfy) |
| `docs/` | Project documentation | Tech lead | This file |

---

## Runtime Architecture

### Application Startup Flow

```mermaid
sequenceDiagram
    Developer->>Docker: make up (or docker compose up -d --build)
    Docker->>PostgreSQL: start + health check
    Docker->>Redis: start + health check
    Docker->>Ntfy: start (push notifications)
    Docker->>Ollama: start (LLM inference, idle)
    Docker->>FastAPI: build image, start app.main:app
    
    FastAPI->>FastAPI: lifespan startup begins
    FastAPI->>Alembic: run migrations (alembic upgrade head)
    Alembic->>PostgreSQL: apply pending schema changes
    FastAPI->>Redis: connect, ping
    FastAPI->>Whisper: load STT model (small.en, int8, pre-warm)
    FastAPI->>Kokoro: load TTS model (af_heart, pre-warm)
    
    FastAPI->>Frontend: ready, serve static files
    Frontend->>Frontend: load index.html
    Frontend->>User: "Disconnected — press Connect & Start"
```

### Startup Sequence (from `app/main.py` lifespan)

1. **Alembic Migrations** (~100ms)
   - Runs `alembic upgrade head`
   - Applies pending schema changes from `app/db/migrations/versions/`
   - Current state: 4 migrations applied (initial schema → timezone aware timestamps)

2. **Redis Connection** (~50ms)
   - Connects to `redis://redis:6379/0` (or `REDIS_URL` env var)
   - Pings to verify connectivity
   - Used for session storage & transient state

3. **STT Model Loading** (~2-3 seconds)
   - Loads Faster-Whisper `small.en` model in CPU int8 mode
   - Pre-warms with 0.5s silence transcription (JIT compilation)
   - Stores globally in `app.voice.stt._model`
   - Sample rate: 16 kHz

4. **TTS Model Loading** (~1-2 seconds)
   - Loads Kokoro TTS pipeline (American English)
   - Pre-warms with dummy synthesis
   - Stores globally in `app.voice.tts._pipeline`
   - Sample rate: 24 kHz

5. **Ready State** (~3-5s total)
   - All components operational
   - `/health` reports `all_ready: true`
   - Frontend can initiate WebSocket connections

### Shutdown Sequence

1. Redis connection closed
2. Database engine disposed
3. Log: "Robo shut down cleanly"

### Service Dependencies

| Service | Container | Role | Health Check | Port |
|---------|-----------|------|--------------|------|
| PostgreSQL | `reception-postgres` | Data persistence | `pg_isready -U reception` | 5433 |
| Redis | `reception-redis` | Session/transient store | `redis-cli ping` | 6379 |
| Ntfy | `reception-ntfy` | Push notifications | N/A (implicit) | 8081 |
| Ollama | `reception-ollama` | LLM inference (future) | N/A | 11434 |
| FastAPI | `reception-api` | Main app server | `/health` endpoint | 8000 |

---

## Configuration & Environment

### Configuration Sources

Robo uses **Pydantic Settings** (from `app/config.py`) with the following precedence:

1. `.env` file (Git-ignored, local machine)
2. `docker-compose.yml` `environment` section (for containers)
3. Pydantic defaults in `Settings` class

### Environment Variables

| Variable | Required | Default | Purpose | Example |
|----------|----------|---------|---------|---------|
| **LLM_MODEL** | No | `groq/llama-4-scout` | LLM model identifier | `groq/llama-4-scout` |
| **LLM_FALLBACK** | No | `groq/llama-4-scout` | Fallback LLM | `groq/llama-4-scout` |
| **GROQ_API_KEY** | Yes* | (empty) | Groq API token for LLM | (set in `.env`) |
| **DATABASE_URL** | No | `postgresql+asyncpg://reception:reception@postgres:5433/reception` | Async PostgreSQL DSN | (docker) or `postgres:5432` (local) |
| **ALEMBIC_DATABASE_URL** | No | `None` | Override for migrations (rarely needed) | N/A |
| **REDIS_URL** | No | `redis://redis:6379/0` | Redis connection string | (docker) or `localhost:6379` (local) |
| **NTFY_HOST** | No | `http://ntfy:8080` | Ntfy server URL | `http://ntfy:8081` (docker) |
| **KIOSK_ID** | No | `kiosk-01` | Unique kiosk identifier | `kiosk-01`, `kiosk-02` |
| **BASE_URL** | No | `http://localhost:8000` | Public app URL | `https://robo.example.com` |

\* `GROQ_API_KEY` required only when LLM features are enabled.

### Docker Compose Environment Overrides

From `docker-compose.yml` (reception-api service):

```yaml
environment:
  DATABASE_URL: postgresql+asyncpg://reception:reception@postgres:5432/reception
  REDIS_URL: redis://redis:6379/0
  NTFY_HOST: http://ntfy:8081
```

Note: Port differences:
- **Local PostgreSQL**: 5433 (host)
- **Container PostgreSQL**: 5432 (internal network)
- **Ntfy**: 8081 (docker-compose service)

### Configuration for Different Environments

#### Development (Local, with Docker)
```bash
# Run migrations
docker compose up postgres redis -d
docker compose exec reception-api alembic upgrade head

# Seed data
docker compose exec reception-api python seed.py

# Start app (hot-reload enabled)
docker compose up reception-api
```

#### Production (Not yet implemented)
- Would require external PostgreSQL + Redis
- SSL/TLS termination (reverse proxy)
- GROQ_API_KEY properly vaulted
- Custom NTFY_HOST or notification service
- Environment-specific docker-compose.prod.yml

---

## Dependency Analysis

### Core Runtime Dependencies

#### FastAPI & Web Framework
- **fastapi** 0.136.3 — Web framework, OpenAPI, dependency injection
- **uvicorn[standard]** 0.49.0 — ASGI app server, WebSocket support
- **websockets** 16.0 — WebSocket protocol layer
- **starlette** (via fastapi) — HTTP & middleware

#### Database & ORM
- **sqlalchemy[asyncio]** 2.0.50 — Async ORM, query builder
- **asyncpg** 0.31.0 — PostgreSQL async driver (required for async SQLAlchemy)
- **psycopg2-binary** 2.9.12 — PostgreSQL sync driver (fallback, also satisfies alembic)
- **alembic** 1.18.4 — Schema migration tool

#### Session & Caching
- **redis[hiredis]** 8.0.0 — Redis async client with C parser

#### Voice Processing Pipeline
- **faster-whisper** 1.2.1 — Fast STT transcription (small.en model)
- **kokoro** 0.9.4 — TTS synthesis (American English)
- **torch** 2.12.0 — PyTorch (required by Silero VAD & Kokoro)
- **torchaudio** 2.11.0 — Audio processing (used by Kokoro)
- **numpy** 2.4.6 — Numerical arrays (audio processing)
- **soundfile** 0.14.0 — WAV file I/O

#### LLM Integration
- **httpx** 0.28.1 — Async HTTP client (for API calls)
- **pydantic** 2.13.4 — Data validation (request/response models)
- **pydantic-settings** 2.14.1 — Environment configuration
- **python-dotenv** 1.2.2 — `.env` file parsing

#### Utilities
- **click** 8.4.1 — CLI utilities (via uvicorn)
- **mako** 1.3.12 — Template engine (alembic migration templates)

### Development-Only Dependencies

```toml
[dependency-groups]
dev = [
    "pytest>=9.0.3",
    "pytest-asyncio>=1.4.0",
]
```

**Note:** Test suite not yet populated. These dependencies are installed but unused.

### Dependency Rationale

| Dependency | Why | Notes |
|-----------|-----|-------|
| asyncpg | Async DB driver, required for concurrent requests | No other option for async PostgreSQL |
| faster-whisper | Fast STT, CPU-efficient (int8), proven quality | Replaces OpenAI Whisper for local inference |
| kokoro | Lightweight TTS, fast inference, streaming support | Replaces cloud TTS (cost + latency) |
| torch + torchaudio | Required by Kokoro & Silero VAD | Heavy dependencies (~2GB+ download) |
| redis | Session storage, ephemeral state | Chosen for low latency, easy local dev |
| sqlalchemy async | Type safety, ORM for complex queries | Required for async/await compatibility |
| pydantic | Config validation, API schema | FastAPI tight integration |

### Known Version Constraints

- **Python 3.11+** required (async features, type hints)
- **PyTorch 2.12** locks heavy transitive deps (numpy, torch)
- **SQLAlchemy 2.0+** breaks 1.x code (async API changes)
- **asyncpg 0.31** requires Python 3.8+ (already satisfied)

---

## Database Architecture

### Schema Overview

Three core tables model the reception domain:

```mermaid
erDiagram
    HOST ||--o{ APPOINTMENT : hosts
    HOST ||--o{ AVAILABILITY_SLOT : manages
    
    HOST {
        uuid id PK "Primary key"
        string name "Full name"
        string email UK "Unique email"
        string department "Department name"
        string notification_channel "Push channel for host"
        boolean is_active "Soft delete flag"
    }
    
    APPOINTMENT {
        uuid id PK
        string appointment_code UK "Unique booking ref"
        string visitor_name "Who is visiting"
        uuid host_id FK "Whom they're visiting"
        string room "Room number"
        int floor "Floor number"
        timestamp scheduled_at TZ "Appointment time (UTC)"
        enum status "scheduled | checked_in | cancelled"
        timestamp check_in_at TZ "Actual check-in time"
        boolean notification_sent "Host notified?"
        boolean notification_acknowledged "Host confirmed?"
    }
    
    AVAILABILITY_SLOT {
        uuid id PK
        uuid host_id FK
        timestamp slot_start TZ "Slot begins"
        timestamp slot_end TZ "Slot ends"
        boolean is_booked "Slot taken?"
    }
```

### Table Details

#### `hosts`
Represents staff members who receive visitors.

```python
class Host(Base):
    __tablename__ = "hosts"
    id: Mapped[uuid.UUID]              # PK
    name: Mapped[str]                  # "Marcus Webb"
    email: Mapped[str]                 # unique@robo.local
    department: Mapped[str]            # "Engineering", "HR"
    notification_channel: Mapped[str]  # ntfy channel, e.g. "marcus-webb"
    is_active: Mapped[bool]            # default True
```

**Usage:** Defines who hosts are, their notification preferences.

#### `appointments`
Visitor appointments with hosts.

```python
class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[uuid.UUID]              # PK
    appointment_code: Mapped[str]      # unique: "APT001"
    visitor_name: Mapped[str]          # "Sarah Chen" (from booking)
    host_id: Mapped[uuid.UUID]         # FK → hosts.id
    room: Mapped[str]                  # "204"
    floor: Mapped[int]                 # 2
    scheduled_at: Mapped[datetime]     # 2026-06-12 14:00:00+00:00 (TZ-aware)
    status: Mapped[AppointmentStatus]  # enum: scheduled, checked_in, cancelled
    check_in_at: Mapped[datetime|None] # actual check-in time (nullable)
    notification_sent: Mapped[bool]    # has host been notified? (default False)
    notification_acknowledged: Mapped[bool] # did host confirm? (default False)
```

**Usage:** Core appointment record. Workflow updates status + timestamps.

#### `availability_slots`
Time slots when hosts are available (used for future scheduling).

```python
class AvailabilitySlot(Base):
    __tablename__ = "availability_slots"
    id: Mapped[uuid.UUID]              # PK
    host_id: Mapped[uuid.UUID]         # FK → hosts.id
    slot_start: Mapped[datetime]       # 2026-06-12 14:00:00+00:00 (TZ-aware)
    slot_end: Mapped[datetime]         # 2026-06-12 15:00:00+00:00
    is_booked: Mapped[bool]            # false = available, true = booked
```

**Usage:** Query available times for booking new appointments.

### Migrations

| ID | Description | Date | Status |
|----|-------------|------|--------|
| 5a0572bb674c | Enable pg_trgm extension | 2026-06-11 | Applied |
| 19f29f6b8ce2 | Initial schema (hosts, appointments, slots) | 2026-06-11 | Applied |
| 50f89190b8fb | Make slot timestamps TZ-aware | 2026-06-11 | Applied |
| ea2e3884ce92 | Make appointment timestamps TZ-aware | 2026-06-12 | Applied |

**Current Head:** `ea2e3884ce92` (timezone-aware appointments)

### Seed Data

File: `seed.py`

**Fixtures (idempotent):**
- 4 Hosts: Marcus Webb, Sarah Lim, Priya Nair, David Chen
- 5 Appointments: mix of scheduled, checked_in, cancelled statuses
- 24 AvailabilitySlots: 3 per host, today + tomorrow, 1-hour slots

**How to run:**
```bash
docker compose exec reception-api python seed.py
```

### Session Store (Redis, Transient)

Not persisted in PostgreSQL; lives in Redis with 30-minute TTL.

```python
# Session key format: session:{kiosk_id}:{session_uuid}
{
    "kiosk_id": "kiosk-01",
    "session_uuid": "550e8400-e29b-41d4-a716-446655440000",
    "created_at": "2026-06-12T10:15:30.123456+00:00",
    "visitor_name": null,
    "current_appointment_id": null,
    "conversation_history": []
}
```

**Managed by:** `app/session/manager.py` (`SessionManager` class)

---

## API Surface

### REST Endpoints

#### Health Check
```
GET /health
```

**Purpose:** Service readiness probe.

**Response:**
```json
{
  "db": "ok",
  "redis": "ok",
  "llm": "pending",
  "stt": "ok",
  "tts": "ok",
  "all_ready": true
}
```

**File:** `app/api/health.py`

#### Ping
```
GET /ping
```

**Purpose:** Simple liveness check.

**Response:**
```json
{"pong": true}
```

**File:** `app/api/health.py`

### WebSocket Endpoints

#### Voice Endpoint
```
WS /ws/voice/{kiosk_id}
```

**Purpose:** Real-time voice conversation stream.

**Parameters:**
- `kiosk_id` (path): Unique kiosk identifier (e.g., "kiosk-01")

**Protocol:** Binary + JSON multiplexed over single connection

**Handshake:**
1. Client connects to `/ws/voice/kiosk-01`
2. Server accepts, sends `{"type": "state", "state": "idle"}`
3. Client streams PCM bytes (16kHz, Int16, 30ms chunks)

**Message Types:**

| Type | Direction | Payload | Notes |
|------|-----------|---------|-------|
| `state` | Server→Client | `{"type": "state", "state": "idle\|listening\|thinking\|speaking"}` | UI state transitions |
| `transcript` | Server→Client | `{"type": "transcript", "text": "..."}` | Recognized speech |
| `response` | Server→Client | `{"type": "response", "text": "..."}` | Agent response text |
| `audio_end` | Server→Client | `{"type": "audio_end"}` | TTS audio complete |
| (binary) | Server→Client | Raw PCM bytes (Int16, 24kHz) | TTS audio stream |
| (binary) | Client→Server | Raw PCM bytes (Int16, 16kHz) | Mic input (30ms chunks) |

**Flow (Day 2 Hardcoded):**

```mermaid
sequenceDiagram
    Frontend->>Backend: connect /ws/voice/kiosk-01
    Backend->>Frontend: {"type": "state", "state": "idle"}
    
    loop Every 30ms
        Frontend->>Backend: binary PCM chunk (16kHz, 480 samples)
        Backend->>Backend: VAD check (Silero)
        Backend->>Backend: Accumulate until silence
    end
    
    Backend->>Backend: STT (Faster-Whisper) — utterance complete
    Backend->>Frontend: {"type": "state", "state": "thinking"}
    Backend->>Frontend: {"type": "transcript", "text": "..."}
    
    Backend->>Backend: Generate response (hardcoded for Day 2)
    Backend->>Frontend: {"type": "response", "text": "Thank you..."}
    Backend->>Frontend: {"type": "state", "state": "speaking"}
    
    Backend->>Backend: TTS (Kokoro) sentence-by-sentence
    Backend->>Frontend: binary audio chunk 1 (24kHz, Int16)
    Backend->>Frontend: binary audio chunk 2
    Backend->>Frontend: {"type": "audio_end"}
    
    Backend->>Frontend: {"type": "state", "state": "idle"}
```

**File:** `app/voice/ws_handler.py`

### Static Files

```
GET /static/{path}
```

**Purpose:** Serve frontend assets (index.html, worklet.js).

**Root:** `frontend/` directory

---

## Voice Processing Pipeline

### Real-Time Voice Flow

```
┌─ Frontend (Web Audio API) ─────────────────────────────────────┐
│                                                                  │
│  Microphone Input (hardware sampling)                          │
│         ↓                                                       │
│  AudioWorklet (process() every ~2.67ms)                        │
│    • float32 audio chunks (128 samples @ 48kHz or 16kHz)       │
│    • Accumulate 480 samples @ 16kHz = 30ms                     │
│    • Convert to Int16 PCM                                      │
│         ↓                                                       │
│  postMessage → main thread (30ms chunks)                       │
│         ↓                                                       │
│  WebSocket.send(binary)                                        │
│         ↓ over network
└─────────────────────────────────────────────────────────────────┘

┌─ Backend (app/voice) ──────────────────────────────────────────┐
│                                                                  │
│  WebSocket receive (30ms PCM chunk, 16kHz, Int16)             │
│         ↓                                                       │
│  1. VAD (Voice Activity Detector) — app/voice/vad.py          │
│     • Silero VAD model (torch, pre-loaded)                    │
│     • Confidence threshold: 0.5                                │
│     • Accumulate speech frames                                 │
│     • Detect 600ms silence → utterance complete               │
│         ↓                                                       │
│  2. STT (Speech-to-Text) — app/voice/stt.py                   │
│     • faster-whisper small.en model (int8, CPU)               │
│     • Input: Int16 PCM (16kHz) → float32 normalized           │
│     • Output: text transcription                               │
│         ↓ (hardcoded for now)                                 │
│  3. Response Generation (Day 2)                                │
│     • Hardcoded: "Thank you, I heard you. I am Robo..."       │
│     • (Future: LLM agent with tool calling)                    │
│         ↓                                                       │
│  4. TTS (Text-to-Speech) — app/voice/tts.py                   │
│     • Kokoro model, American English (af_heart voice)         │
│     • Split response into sentences (min 4 words)              │
│     • Synthesize sentence-by-sentence → streaming             │
│     • Output: Int16 PCM (24kHz)                                │
│         ↓                                                       │
│  WebSocket.send(binary audio chunk) — iterate until complete  │
│  WebSocket.send(json {"type": "audio_end"})                   │
│         ↓ over network
└─────────────────────────────────────────────────────────────────┘

┌─ Frontend (playback) ───────────────────────────────────────────┐
│                                                                  │
│  Accumulate PCM chunks                                         │
│         ↓                                                       │
│  playNext() — create AudioBuffer                              │
│    • Decode Int16 → float32                                    │
│    • Create audio buffer                                       │
│    • Play via destination (speakers)                           │
│         ↓ (chain onended handlers)                            │
│  When complete → await idle                                    │
│         ↓                                                       │
│  Ready for next utterance                                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Component Details

#### Voice Activity Detection (VAD)

**File:** `app/voice/vad.py`

**Model:** Silero VAD (torch hub, force_reload=False for caching)

**Configuration:**
- Chunk size: 30ms (480 samples @ 16kHz)
- Silence threshold: 600ms (20 consecutive silent chunks)
- Confidence threshold: 0.5 (binary classification: speech vs noise)
- Stateful per-session (resets on new connection)

**Output:**
- `is_speaking`: True when speech detected
- `utterance_bytes`: Complete utterance when silence detected (None otherwise)

#### Speech-to-Text (STT)

**File:** `app/voice/stt.py`

**Model:** Faster-Whisper small.en (CPU int8)

**Configuration:**
- Sample rate: 16 kHz (required by Whisper)
- Compute type: int8 (2x faster than float32 on CPU, minimal quality loss)
- Beam size: 1 (greedy decoding for speed)
- VAD: Disabled (we handle VAD ourselves)
- Language: English (hardcoded)

**Latency:** ~0.5-1.5s per utterance (depends on length)

**Pre-warming:** Dummy 0.5s silence transcription on startup (JIT compilation)

#### Text-to-Speech (TTS)

**File:** `app/voice/tts.py`

**Model:** Kokoro (American English, af_heart voice)

**Configuration:**
- Sample rate: 24 kHz (Kokoro native)
- Voice: `af_heart` (warm, neutral tone suitable for reception)
- Sentence splitting: Min 4 words per sentence
- Streaming: Yield per-sentence PCM bytes (low perceived latency)

**Latency:** ~200-400ms per sentence

**Output normalization:** float32 → Int16 PCM

#### Session Management

**File:** `app/session/manager.py`

**Storage:** Redis (per-connection, 30-minute TTL)

**Schema:**
```python
{
    "kiosk_id": "kiosk-01",
    "session_uuid": "uuid",
    "created_at": "ISO8601",
    "visitor_name": null,
    "current_appointment_id": null,
    "conversation_history": []
}
```

**Methods:**
- `create(kiosk_id)` → session_uuid
- `get(kiosk_id, session_uuid)` → dict
- `update(kiosk_id, session_uuid, updates)` → void
- `delete(kiosk_id, session_uuid)` → void

---

## Workflow Documentation

### Implemented Workflows

#### 1. Standard Visitor Check-In (Partial — Day 2)

**Entry Point:** WebSocket connection `/ws/voice/kiosk-01`

**Steps:**
1. Kiosk sends audio stream
2. Backend detects voice activity (VAD)
3. Transcribe to text (STT)
4. Generate response (hardcoded for Day 2)
5. Synthesize audio (TTS)
6. Stream audio back to frontend
7. Repeat

**Current Status:** ✅ Voice loop functional, response hardcoded

**Next Steps:**
- Integrate appointment lookup (match visitor name to appointment)
- Integrate host notification (Ntfy)
- Implement LLM-based response generation
- Handle name mismatches and edge cases

**Diagram:**
```
Visitor speaks → VAD detects → STT transcribes
                                    ↓
                           (future) LLM agent
                                    ↓
                          TTS synthesizes response
                                    ↓
                           Speaker plays audio
                                    ↓
                          Back to listening state
```

#### 2. Session Management

**Entry Point:** WebSocket connection

**Steps:**
1. `SessionManager.create(kiosk_id)` → session_uuid
2. Store in Redis with 30-min TTL
3. Track conversation history
4. On disconnect, clean up

**Current Status:** ✅ Session created/deleted, structure ready

**Next Steps:**
- Populate `conversation_history` with turns
- Use session context in LLM prompt
- Implement session recovery on reconnect

### Planned Workflows (Not Yet Implemented)

#### Appointment Lookup
- [ ] Visitor says name → match against appointments DB
- [ ] Retrieve host info & room location
- [ ] Confirm appointment details
- [ ] Trigger host notification

#### Host Notification (Ntfy)
- [ ] On confirmed appointment, publish to `ntfy_host:channel`
- [ ] Host sees "Visitor X arriving for appointment Y"
- [ ] Host can acknowledge via Ntfy or dashboard
- [ ] Record `notification_acknowledged` timestamp

#### Multi-Turn Conversation
- [ ] Maintain conversation history in session
- [ ] Pass context to LLM agent
- [ ] Handle clarification & edge cases
- [ ] Decision tree for wayfinding, rescheduling, etc.

---

## Integration Mapping

### External Services

#### Groq API (LLM)
- **Purpose:** Intelligent response generation (future)
- **Model:** groq/llama-4-scout (configurable)
- **Authentication:** GROQ_API_KEY environment variable
- **Usage:** Not yet integrated (hardcoded response on Day 2)
- **File:** (TBD) `app/agent/llm.py`
- **Latency:** ~500ms-1s for LLM inference

#### Ntfy (Push Notifications)
- **Purpose:** Notify hosts of arriving visitors
- **Service URL:** `NTFY_HOST` (default: `http://ntfy:8081`)
- **Protocol:** HTTP POST to `/channel_name`
- **Authentication:** None (optional auth supported)
- **Usage:** Not yet integrated
- **File:** (TBD) `app/notifications/ntfy.py`
- **Configuration:** `config/ntfy/server.yml`

#### Ollama (Local LLM, Optional)
- **Purpose:** Alternative LLM inference (local, offline)
- **Service URL:** `http://ollama:11434` (docker-compose)
- **Models:** Any Ollama-supported model (e.g., llama2, mistral)
- **Usage:** Not yet integrated (optional, future consideration)
- **Note:** Runs in Docker but not required for MVP

#### PostgreSQL Database
- **Purpose:** Persistent storage (hosts, appointments, slots)
- **Driver:** asyncpg (async), psycopg2 (migrations)
- **Connection:** `DATABASE_URL` (default: `postgresql+asyncpg://...`)
- **Health Check:** `SELECT 1` (from health endpoint)

#### Redis
- **Purpose:** Session storage, transient state, caching
- **Connection:** `REDIS_URL` (default: `redis://redis:6379/0`)
- **Usage:** Session manager, conversation history (future)
- **Health Check:** `PING` command

---

## Developer Workflow Guide

### Prerequisites

- Python 3.11+ (verify: `python --version`)
- Docker & Docker Compose (verify: `docker --version`)
- Git
- Text editor (VS Code recommended)

### Setup

#### 1. Clone & Install Dependencies

```bash
git clone <repo>
cd reception-robo

# (Optional) Create Python venv if not using Docker
python3.11 -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install deps locally (for IDE support)
pip install -r requirements.txt
```

#### 2. Configure Environment

```bash
# Copy example and edit
cp .env.example .env

# Add Groq API key (required if testing LLM, else optional)
# GROQ_API_KEY=...
```

#### 3. Start Infrastructure

```bash
# Build images + start containers
make up

# Or manually:
docker compose up -d --build

# Check health
docker compose ps
docker compose logs robo-api
```

#### 4. Seed Database

```bash
make seed

# Or manually:
docker compose exec reception-api python seed.py
```

#### 5. Verify Health

```bash
# Check all services ready
curl http://localhost:8000/health

# Expected response (all_ready: true)
{
  "db": "ok",
  "redis": "ok",
  "stt": "ok",
  "tts": "ok",
  "llm": "pending",
  "all_ready": true
}
```

#### 6. Open Frontend

```bash
# Open browser
http://localhost:8000/static/index.html

# Click "Connect & Start", allow microphone, speak!
```

### Common Developer Commands

| Task | Command | Notes |
|------|---------|-------|
| **Start stack** | `make up` | Builds image, starts all services |
| **Stop stack** | `make down` | Stops containers, keeps volumes |
| **Reset stack** | `make reset` | Down + purge volumes + rebuild |
| **View logs** | `make logs` | Tail app logs (Ctrl+C to exit) |
| **Seed data** | `make seed` | Populate 4 hosts, 5 appointments |
| **Run tests** | `make smoke` | Pytest integration tests (empty TBD) |
| **DB migrations** | `docker compose exec reception-api alembic upgrade head` | Apply pending migrations |
| **Create migration** | `docker compose exec reception-api alembic revision --autogenerate -m "message"` | Auto-detect schema changes |
| **Direct shell** | `docker compose exec reception-api bash` | Debug shell access |

### Development Tips

#### Hot Reload
- App runs with `--reload` flag (Dockerfile CMD)
- Edit `app/*.py` → saved → auto-restart
- Frontend (HTML/JS) requires manual browser reload

#### Debug Mode
```bash
# SSH into container
docker compose exec reception-api bash

# Run Python interactively
python

# Import and test
from app.db.models import Host
from app.db.session import AsyncSessionLocal
import asyncio

async def test():
    async with AsyncSessionLocal() as session:
        hosts = await session.execute(select(Host))
        print(hosts.scalars().all())

asyncio.run(test())
```

#### View Database
```bash
# Connect to PostgreSQL directly
docker compose exec postgres psql -U reception -d reception

# List tables
\dt

# Query appointments
SELECT appointment_code, visitor_name, status FROM appointments;
```

#### Monitor Redis
```bash
# Connect to Redis
docker compose exec redis redis-cli

# List all keys
keys *

# Inspect session
get session:kiosk-01:550e8400-e29b-41d4-a716-446655440000
```

### Code Organization Best Practices

**Imports:**
```python
# Absolute imports from app package root
from app.db.session import get_session
from app.config import settings

# Avoid relative imports (confusing in async context)
# ❌ from .models import Host
# ✅ from app.db.models import Host
```

**Async/Await:**
```python
# Always use async context managers
async with AsyncSessionLocal() as session:
    result = await session.execute(...)

# Never block in async functions
# ❌ import time; time.sleep(1)
# ✅ import asyncio; await asyncio.sleep(1)
```

**Error Handling:**
- Global exception handler catches 500 errors (see `app/main.py`)
- Log with `logger.exception(...)` for stack traces
- Return appropriate HTTP status codes

---

## Implemented Features

### ✅ Complete

| Feature | Status | Files | Notes |
|---------|--------|-------|-------|
| **Voice WebSocket Endpoint** | Complete | `app/voice/ws_handler.py` | Bidirectional PCM + JSON |
| **VAD (Voice Activity Detection)** | Complete | `app/voice/vad.py` | Silero VAD, stateful per session |
| **STT (Speech-to-Text)** | Complete | `app/voice/stt.py` | Faster-Whisper small.en (int8) |
| **TTS (Text-to-Speech)** | Complete | `app/voice/tts.py` | Kokoro, sentence-by-sentence streaming |
| **Session Management** | Complete | `app/session/manager.py` | Redis-backed, 30-min TTL |
| **Database Models** | Complete | `app/db/models.py` | Host, Appointment, AvailabilitySlot |
| **Database Migrations** | Complete | `app/db/migrations/versions/` | 4 migrations, Alembic setup |
| **Health Endpoint** | Complete | `app/api/health.py` | Service readiness probe |
| **Frontend Test Client** | Complete | `frontend/index.html` + `frontend/worklet.js` | Web Audio API, AudioWorklet |
| **Docker Compose Setup** | Complete | `docker-compose.yml` | 5 services (postgres, redis, ntfy, ollama, app) |
| **Seed Script** | Complete | `seed.py` | 4 hosts, 5 appointments, 24 slots |
| **Lifespan Management** | Complete | `app/main.py` | Migrations, model loading, startup/shutdown |
| **Configuration (Pydantic)** | Complete | `app/config.py` | Env var parsing, settings validation |

### ✅ Partial (Day 2 MVP)

| Feature | Status | Files | Gaps |
|---------|--------|-------|------|
| **Response Generation** | Partial | `app/voice/ws_handler.py` | Hardcoded response, no LLM integration |
| **Conversation History** | Partial | `app/session/manager.py` | Schema defined, not populated |
| **API Layer** | Partial | `app/api/` | Only health/ping, no CRUD endpoints |

### 📋 Stub / Placeholder

| Component | Status | Files | Purpose |
|-----------|--------|-------|---------|
| **LLM Agent** | Stub | `app/agent/` (empty) | Future intelligent responses |
| **Tool Calling** | Stub | `app/tools/` (empty) | Future structured tools (appointment lookup, etc.) |
| **Notifications** | Stub | `app/notifications/` (empty) | Future Ntfy integration |
| **Wayfinding** | Stub | `app/wayfinding/` (empty) | Future directions, maps |
| **Test Suite** | Stub | `tests/` (empty) | pytest + pytest-asyncio configured but no tests |

---

## Known Gaps & Work In Progress

### Critical Missing Pieces (Blocking Production)

| Gap | Severity | Impact | Fix |
|-----|----------|--------|-----|
| **No Appointment Lookup** | Critical | Visitor check-in doesn't find appointment | Implement appointment query by name + date |
| **No Host Notification** | Critical | Hosts don't know visitors arrived | Implement Ntfy integration |
| **Hardcoded Response** | Critical | No intelligent dialogue | Implement LLM agent with Groq API |
| **No LLM Integration** | Critical | Agent can't make decisions | Wire Groq SDK to ws_handler |
| **No Error Recovery** | High | Crashes on edge cases (bad audio, timeouts) | Add retry logic, graceful degradation |
| **No Authentication** | High | Any kiosk can access any session | Implement kiosk token validation |

### Quality Issues

| Issue | Severity | Notes |
|-------|----------|-------|
| **No Test Suite** | High | 0% coverage, test infrastructure in place but empty |
| **Limited Logging** | Medium | Hard to debug production issues |
| **No Rate Limiting** | Medium | Could be DoSed by malicious clients |
| **Minimal Validation** | Medium | User inputs not sanitized |
| **No Metrics/Monitoring** | Medium | Can't observe system health in production |

### Technical Debt

| Item | Notes |
|------|-------|
| **Unused `main.py` Root** | File at repository root is unused, should delete or clarify |
| **Alembic Config Location** | `alembic.ini` at root, migrations in `app/db/` (asymmetric) |
| **Frontend Hardcoding** | `KIOSK_ID`, `WS_URL` hardcoded in HTML, should be config-driven |
| **Response Pipeline** | DAG is linear; no branching for clarification questions |
| **Ollama Unused** | Running in docker-compose but not integrated |

### Features Deferred (Post-MVP)

- [ ] Calendar integration (checking real host availability)
- [ ] Multi-language support (only English for now)
- [ ] Screen interaction (only voice for now)
- [ ] Wayfinding (directions to room)
- [ ] Analytics (visit tracking, no-show analysis)
- [ ] Admin dashboard
- [ ] Mobile app
- [ ] Integration with corporate directory (LDAP, AD)

---

## End-to-End Request Flow

### Scenario: Visitor Checks In

**Setup:**
- Visitor: Sarah Chen
- Appointment code: APT001
- Scheduled: 2026-06-12 14:00 UTC
- Host: Marcus Webb
- Appointment already in database (from seed)

**Request Flow:**

```mermaid
sequenceDiagram
    actor V as Visitor
    participant F as Frontend
    participant W as WebSocket
    participant B as Backend
    participant VAD as VAD/STT
    participant DB as PostgreSQL
    participant R as Redis
    
    V->>F: Click "Connect & Start"
    activate F
    F->>F: AudioContext, getUserMedia()
    F->>W: WebSocket /ws/voice/kiosk-01
    activate W
    W->>B: Accept connection
    B->>R: SessionManager.create("kiosk-01")
    B->>F: {"type": "state", "state": "idle"}
    
    V->>V: Speak: "Hi, I have an appointment"
    V->>F: Audio stream (PCM)
    F->>W: 30ms chunk (480 samples, Int16, 16kHz)
    
    loop Until utterance complete
        W->>B: Receive chunk
        B->>VAD: VAD.process_chunk()
        VAD-->>B: is_speaking=true, utterance_bytes=None
    end
    
    B->>F: {"type": "state", "state": "listening"}
    B->>F: {"type": "state", "state": "thinking"}
    
    B->>VAD: STT.transcribe(utterance_bytes)
    VAD-->>B: "Hi, I have an appointment"
    B->>F: {"type": "transcript", "text": "Hi, I have an appointment"}
    
    Note over B: Day 2: hardcoded response (no LLM)
    B->>B: response = "Thank you, I heard you. I am Robo..."
    
    B->>F: {"type": "response", "text": "Thank you..."}
    B->>F: {"type": "state", "state": "speaking"}
    
    B->>B: TTS.synthesise_stream(response)
    B-->>B: Split into sentences
    B-->>B: Synthesize each (Kokoro)
    B->>W: binary PCM chunk 1 (Int16, 24kHz)
    B->>W: binary PCM chunk 2
    B->>W: {"type": "audio_end"}
    
    W->>F: binary audio
    F->>F: AudioBuffer, play()
    
    B->>F: {"type": "state", "state": "idle"}
    
    Note over V,B: Ready for next turn...
```

**Code Execution:**

1. **Connection accepted** (`app/voice/ws_handler.py` line 23)
   ```python
   await websocket.accept()
   session_uuid = await session_manager.create(kiosk_id)
   ```

2. **VAD processes chunks** (until silence detected)
   ```python
   is_speaking, utterance_bytes = vad.process_chunk(message)
   # Returns (True, None) while speaking
   # Returns (False, PCM_bytes) when silence detected
   ```

3. **STT transcribes** (when utterance complete)
   ```python
   transcript = await transcribe(utterance_bytes)
   # Faster-Whisper inference: ~500ms
   ```

4. **Response generated** (Day 2: hardcoded)
   ```python
   response_text = HARDCODED_RESPONSE
   # Future: LLM agent will query appointments here
   ```

5. **TTS streams audio**
   ```python
   async for audio_chunk in synthesise_stream(response_text):
       await websocket.send_bytes(audio_chunk)
   ```

6. **Cycle repeats** (back to idle)

### Database Interactions (Future)

Once LLM + appointment lookup implemented:

```python
# Pseudo-code (not yet implemented)
from sqlalchemy import select
from app.db.models import Appointment

async with AsyncSessionLocal() as session:
    # Find appointment by visitor name
    stmt = select(Appointment).where(
        Appointment.visitor_name.ilike(f"%{visitor_name}%"),
        Appointment.status == AppointmentStatus.scheduled
    )
    appointments = await session.scalars(stmt)
    
    if appointments:
        appt = appointments[0]  # Could be multiple
        # Return to LLM: room, host, time
        # Update: status = checked_in, check_in_at = now
        appt.status = AppointmentStatus.checked_in
        appt.check_in_at = datetime.now(timezone.utc)
        await session.commit()
        
        # Notify host via Ntfy
        notify_host(host_id=appt.host_id, visitor=appt.visitor_name)
```

### Performance Characteristics

| Stage | Latency | Notes |
|-------|---------|-------|
| **VAD (per chunk)** | ~10ms | Real-time, per-30ms PCM |
| **VAD (utterance detection)** | ~600ms | Silence threshold |
| **STT (transcription)** | 0.5–1.5s | Depends on audio length; small.en + int8 optimized |
| **LLM (response)** | 0.5–2s | Groq API (not yet integrated) |
| **TTS (synthesis)** | 0.2–0.4s per sentence | Kokoro streaming |
| **Network (round-trip)** | ~50ms | Local Docker; varies with client distance |
| **Total turn time** | ~2–5s | STT → LLM → TTS + network |

**User Experience:** Visitor speaks → ~1s transcription → ~1s LLM → ~2s TTS → Response heard ≈ 4 seconds total (acceptable for kiosk)

---

## Appendix: File Reference Guide

### Core Application

| File | LOC | Purpose |
|------|-----|---------|
| `app/main.py` | 70 | FastAPI app, lifespan, routes, exception handler |
| `app/config.py` | 25 | Pydantic Settings, env var parsing |

### Voice Pipeline

| File | LOC | Purpose |
|------|-----|---------|
| `app/voice/ws_handler.py` | 140 | WebSocket orchestrator, state machine |
| `app/voice/vad.py` | 80 | Silero VAD, voice detection, buffering |
| `app/voice/stt.py` | 65 | Faster-Whisper, transcription |
| `app/voice/tts.py` | 95 | Kokoro, synthesis, streaming |

### Data Layer

| File | LOC | Purpose |
|------|-----|---------|
| `app/db/models.py` | 60 | SQLAlchemy ORM (Host, Appointment, AvailabilitySlot) |
| `app/db/session.py` | 20 | AsyncSession factory |
| `app/db/base.py` | 5 | Declarative base |

### API & Infrastructure

| File | LOC | Purpose |
|------|-----|---------|
| `app/api/health.py` | 35 | Health & ping endpoints |
| `app/session/manager.py` | 60 | Redis session store |

### Frontend

| File | LOC | Purpose |
|------|-----|---------|
| `frontend/index.html` | 85 | Test client, Web Audio API |
| `frontend/worklet.js` | 30 | AudioWorklet processor |

### Configuration & Deployment

| File | Notes |
|------|-------|
| `docker-compose.yml` | 5 services, volumes, env overrides |
| `DockerFile` | Python 3.11-slim, pip install, uvicorn CMD |
| `Makefile` | Developer shortcuts |
| `pyproject.toml` | Project metadata, dependencies |
| `requirements.txt` | Frozen deps (auto-generated by uv) |
| `alembic.ini` | Alembic configuration |
| `seed.py` | Initial data loader |
| `.env.example` | Template for local env vars |

### Migrations

| File | Revision | Purpose |
|------|----------|---------|
| `app/db/migrations/versions/5a0572bb674c_*.py` | 5a0572bb674c | Enable pg_trgm |
| `app/db/migrations/versions/19f29f6b8ce2_*.py` | 19f29f6b8ce2 | Initial schema |
| `app/db/migrations/versions/50f89190b8fb_*.py` | 50f89190b8fb | Slot timezone awareness |
| `app/db/migrations/versions/ea2e3884ce92_*.py` | ea2e3884ce92 | Appointment timezone awareness |

---

## Quick Reference: Commands & URLs

### Make Targets
```bash
make up              # Start stack
make down            # Stop stack
make reset           # Purge + restart
make seed            # Populate DB
make logs            # Tail app logs
make smoke           # Run tests (empty)
```

### URLs
```
Frontend:        http://localhost:8000/static/index.html
WebSocket:       ws://localhost:8000/ws/voice/kiosk-01
Health:          http://localhost:8000/health
Ntfy (UI):       http://localhost:8081
PostgreSQL:      localhost:5433
Redis:           localhost:6379
Ollama:          http://localhost:11434
```

### Environment
```
DATABASE_URL     postgresql+asyncpg://reception:reception@postgres:5432/reception
REDIS_URL        redis://redis:6379/0
KIOSK_ID         kiosk-01
GROQ_API_KEY     (required for LLM, set in .env)
```

---

**End of Document**

Generated: June 12, 2026  
Version: 1.0  
Status: Active — Ready for developer onboarding
