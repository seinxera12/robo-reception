# Robo Reception Assistant — Setup Guide

**Version:** 1.0  
**Last Updated:** June 13, 2026  
**Target Audience:** Any developer setting up the project from a fresh clone

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone & Repository Layout](#2-clone--repository-layout)
3. [Environment Configuration](#3-environment-configuration)
4. [Start the Stack](#4-start-the-stack)
5. [Verify Services Are Healthy](#5-verify-services-are-healthy)
6. [Run Database Migrations](#6-run-database-migrations)
7. [Seed the Database](#7-seed-the-database)
8. [Verify the Application Is Ready](#8-verify-the-application-is-ready)
9. [Open the Frontend](#9-open-the-frontend)
10. [Stopping & Resetting](#10-stopping--resetting)
11. [Local Development Without Docker](#11-local-development-without-docker-optional)
12. [Known Issues & Gotchas](#12-known-issues--gotchas)
13. [Port Reference](#13-port-reference)
14. [Service Credentials Reference](#14-service-credentials-reference)

---

## 1. Prerequisites

Install the following tools before you begin. Verify each one by running the check command.

| Tool | Minimum Version | Check Command | Install Link |
|------|----------------|---------------|--------------|
| **Docker** | 24+ | `docker --version` | https://docs.docker.com/get-docker/ |
| **Docker Compose** | v2 (bundled with Docker Desktop) | `docker compose version` | Bundled with Docker Desktop |
| **Git** | Any | `git --version` | https://git-scm.com/ |
| **Python** | 3.11+ | `python --version` | https://www.python.org/downloads/ (only needed for local dev, Step 11) |

> **Windows users:** Use PowerShell or Windows Terminal. WSL2 is recommended for the best Docker experience but not required.

> **GPU / CPU:** The voice models (Whisper STT, Kokoro TTS) run on **CPU** by default using int8 quantisation. No GPU is required. First-run model download may take a few minutes depending on your internet connection.

---

## 2. Clone & Repository Layout

```bash
git clone <your-repo-url>
cd robo-reception
```

After cloning, the workspace root contains:

```
robo-reception/
├── app/                  # FastAPI application (Python)
├── frontend/             # Browser test client (HTML + JS)
├── config/ntfy/          # Ntfy push-notification config
├── docs/                 # Documentation (you are here)
├── docker-compose.yml    # Full-stack service definitions
├── DockerFile            # Python 3.11-slim app image
├── alembic.ini           # Alembic migration entry point
├── requirements.txt      # Pinned pip dependencies
├── seed.py               # Database fixture loader
├── .env.example          # Environment variable template
└── Makefile              # Developer shortcuts
```

---

## 3. Environment Configuration

The application reads its configuration from a `.env` file in the repository root. This file is **git-ignored** and must be created from the provided template.

```bash
cp .env.example .env
```

Open `.env` and review/fill in the values:

```dotenv
# --- LLM (optional for now; required when LLM features are enabled) ---
LLM_MODEL=groq/llama-4-scout
LLM_FALLBACK=groq/llama-4-scout
GROQ_API_KEY=                     # Leave blank for Day-2 MVP; fill in when LLM is wired up

# --- Database (local dev, connecting from host machine) ---
DATABASE_URL=postgresql+asyncpg://reception:reception@localhost:5433/reception

# --- Redis ---
REDIS_URL=redis://localhost:6379/0

# --- Notifications ---
NTFY_HOST=http://localhost:8081

# --- Kiosk identity ---
KIOSK_ID=kiosk-01
BASE_URL=http://localhost:8000
```

### Important: DATABASE_URL in containers vs. on host

Docker Compose **overrides** `DATABASE_URL` and `REDIS_URL` for the `reception-api` container so it can reach the other containers by their service names:

```yaml
# docker-compose.yml — reception-api environment block
DATABASE_URL: postgresql+asyncpg://reception:reception@postgres:5432/reception
REDIS_URL: redis://redis:6379/0
NTFY_HOST: http://ntfy:8081
```

Your `.env` file values are used when running scripts **directly on your host** (e.g., `python seed.py`). For running inside Docker you do not need to change anything — the compose override takes precedence automatically.

---

## 4. Start the Stack

This single command builds the app image and starts all five services:

```bash
docker compose up -d --build
```

Services started:

| Container | Image | Role |
|-----------|-------|------|
| `reception-postgres` | postgres:16-alpine | PostgreSQL 16 database |
| `reception-redis` | redis:7-alpine | Session / transient state store |
| `reception-ntfy` | binwiederhier/ntfy:latest | Push notifications |
| `reception-ollama` | ollama/ollama:latest | Local LLM inference (idle, future use) |
| `reception-api` | Built from `DockerFile` | FastAPI application |

> **First build:** Docker will download base images and install all Python dependencies (including PyTorch ~2 GB). Expect 5–15 minutes on a fresh machine. Subsequent builds are fast due to layer caching.

### Using Make (convenience shortcut)

```bash
make up     # equivalent to: docker compose up -d --build
```

> **Note:** The `Makefile` contains a bug — `make seed` and `make logs` reference the service name `robo-api`, but the correct container name in `docker-compose.yml` is `reception-api`. Use the explicit `docker compose` commands shown in this guide until the Makefile is fixed.

---

## 5. Verify Services Are Healthy

Check that all containers are running and the infrastructure services have passed their health checks before proceeding:

```bash
docker compose ps
```

Expected output (all services `Up`, postgres and redis show `(healthy)`):

```
NAME                   IMAGE                         STATUS
reception-api          robo-reception-reception-api  Up
reception-ntfy         binwiederhier/ntfy            Up
reception-ollama       ollama/ollama                 Up
reception-postgres     postgres:16-alpine            Up (healthy)
reception-redis        redis:7-alpine                Up (healthy)
```

If postgres or redis are not `healthy` yet, wait 15–30 seconds and re-run `docker compose ps`. The `reception-api` container will not start until both pass their health checks.

### Tail the app logs

```bash
docker compose logs -f reception-api
```

On first startup the application will:

1. Apply database migrations (Alembic)
2. Connect to Redis
3. Download and load the Whisper STT model (`small.en`, ~250 MB, int8) — **up to 2–3 minutes on first run**
4. Download and load the Kokoro TTS model — **up to 1–2 minutes on first run**

When ready, you will see:

```
✓ Robo ready — all systems operational!
Frontend: http://localhost:8000/static/index.html
WebSocket: ws://localhost:8000/ws/voice/kiosk-01
Health: http://localhost:8000/health
Waiting for connections... (Press CTRL+C to shut down)
```

---

## 6. Run Database Migrations

Migrations are run **automatically** during application startup via Alembic (`alembic upgrade head`). You do not normally need to run them manually.

If you need to run migrations manually (e.g., after adding a new migration file):

```bash
docker compose exec reception-api alembic upgrade head
```

### Current migration history

| Revision | Description |
|----------|-------------|
| `5a0572bb674c` | Enable `pg_trgm` extension |
| `19f29f6b8ce2` | Initial schema (hosts, appointments, availability_slots) |
| `50f89190b8fb` | Make availability_slot timestamps timezone-aware |
| `ea2e3884ce92` | Make appointment timestamps timezone-aware ← **HEAD** |

### Creating a new migration

If you change a SQLAlchemy model in `app/db/models.py`, auto-generate a migration:

```bash
docker compose exec reception-api alembic revision --autogenerate -m "describe your change"
```

Review the generated file in `app/db/migrations/versions/` before applying it.

---

## 7. Seed the Database

Seed data populates the database with fixture records for development and testing. The script is **idempotent** — running it more than once is safe.

```bash
docker compose exec reception-api python seed.py
```

Expected output:

```
Seeded: 4 hosts, 5 appointments, 24 slots
```

### What gets seeded

| Table | Records | Details |
|-------|---------|---------|
| `hosts` | 4 | Marcus Webb (Engineering), Sarah Lim (Engineering), Priya Nair (HR), David Chen (Management) |
| `appointments` | 5 | Mix of `scheduled`, `checked_in`, `cancelled` statuses; APT001–APT005 |
| `availability_slots` | 24 | 3 slots per host × 2 days (today + tomorrow), 1-hour blocks from 14:00 UTC |

### Resetting seed data

To wipe and re-seed from scratch:

```bash
docker compose down -v          # removes all named volumes (destroys DB data)
docker compose up -d --build
docker compose exec reception-api python seed.py
```

---

## 8. Verify the Application Is Ready

Hit the health endpoint to confirm all subsystems are operational:

```bash
curl http://localhost:8000/health
```

Expected response (`all_ready: true`):

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

Field meanings:

| Field | `ok` means… |
|-------|-------------|
| `db` | PostgreSQL `SELECT 1` succeeded |
| `redis` | Redis `PING` succeeded |
| `llm` | Always `"pending"` — LLM not yet integrated |
| `stt` | Whisper model is loaded in memory |
| `tts` | Kokoro model is loaded in memory |
| `all_ready` | `true` when db, redis, stt, and tts are all `ok` |

If any field shows an error, check `docker compose logs reception-api` for the relevant startup failure.

---

## 9. Open the Frontend

Once `all_ready` is `true`, open the test client in your browser:

```
http://localhost:8000/static/index.html
```

1. Click **"Connect & Start"**
2. Allow microphone access when the browser prompts
3. Speak into your microphone
4. The system will transcribe your speech, generate a response (currently hardcoded), synthesise audio, and play it back

The browser console will show WebSocket state transitions: `idle → listening → thinking → speaking → idle`.

---

## 10. Stopping & Resetting

### Stop all containers (preserves data volumes)

```bash
docker compose down
# or: make down
```

### Stop and destroy all data (full reset)

```bash
docker compose down -v
# or: make reset
```

> **Warning:** `down -v` deletes the postgres, redis, and ollama volumes permanently. You will need to re-seed after bringing the stack back up.

### Restart a single service

```bash
docker compose restart reception-api
```

---

## 11. Local Development Without Docker (Optional)

Running the app directly on your host lets you use a debugger or iterate faster without rebuilding images.

### Requirements

- Python 3.11+
- A running PostgreSQL 16 instance on port `5433` (or adjust `DATABASE_URL`)
- A running Redis 7 instance on port `6379`

You can still run only the infrastructure in Docker:

```bash
docker compose up -d postgres redis ntfy
```

### Install Python dependencies

Using `uv` (recommended, fastest):

```bash
pip install uv
uv sync
```

Or with plain pip:

```bash
pip install -r requirements.txt
```

### Configure the environment

Ensure your `.env` uses `localhost` addresses (this is the default in `.env.example`):

```dotenv
DATABASE_URL=postgresql+asyncpg://reception:reception@localhost:5433/reception
REDIS_URL=redis://localhost:6379/0
NTFY_HOST=http://localhost:8081
```

### Run migrations locally

```bash
alembic upgrade head
```

### Seed locally

```bash
python seed.py
```

### Start the app

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Hot-reload is active — saving any `.py` file under `app/` will automatically restart the server.

---

## 12. Known Issues & Gotchas

### Makefile service name mismatch

`make seed` and `make logs` use `robo-api` as the container target, but the actual service name in `docker-compose.yml` is `reception-api`. These make targets will fail with *no such service*. Use the explicit commands instead:

```bash
# Instead of: make seed
docker compose exec reception-api python seed.py

# Instead of: make logs
docker compose logs -f reception-api
```

### PostgreSQL exposed on port 5433 (not 5432)

The host-side port is `5433` to avoid conflicts with a locally installed PostgreSQL. Inside the Docker network the service listens on `5432` as normal. The `docker-compose.yml` environment block already sets the correct internal URL for the app container.

### STT / TTS model download on first run

Whisper and Kokoro models are downloaded from the internet the first time they are needed. This happens inside the container at startup. Expect **3–5 minutes** on a slow connection. Subsequent starts use the cached files inside the container filesystem (or a mounted volume if you add one).

### `.env` file is git-ignored

The repository ships `.env.example`. You **must** copy it to `.env` before starting the stack. The application will start with Pydantic defaults if `.env` is absent, but those defaults point to Docker-internal hostnames (`postgres`, `redis`) which won't resolve on the host.

### `GROQ_API_KEY` is optional for now

The LLM is not yet integrated. You can leave `GROQ_API_KEY` blank. The `/health` endpoint will always return `"llm": "pending"` — this is expected.

### `main.py` at repository root

There is an unused `main.py` at the repository root. The real application entry point is `app/main.py`. The root file can be ignored.

### `alembic.ini` location

`alembic.ini` sits at the repository root and points to `app/db/migrations` as the script location. Always run Alembic from the repository root (or from inside the container where `/app` is the working directory).

---

## 13. Port Reference

| Service | Host Port | Container Port | Usage |
|---------|-----------|----------------|-------|
| FastAPI app | **8000** | 8000 | REST API, WebSocket, static files |
| PostgreSQL | **5433** | 5432 | Database (note: non-standard host port) |
| Redis | **6379** | 6379 | Session store |
| Ntfy | **8081** | 80 | Push notification web UI |
| Ollama | **11434** | 11434 | LLM inference (idle, future use) |

---

## 14. Service Credentials Reference

| Service | Username | Password | Database |
|---------|----------|----------|----------|
| PostgreSQL | `reception` | `reception` | `reception` |
| Redis | — (no auth) | — | DB `0` |
| Ntfy | — (no auth in dev) | — | — |

Connect to PostgreSQL directly for inspection:

```bash
docker compose exec postgres psql -U reception -d reception
```

Useful PSQL commands:

```sql
\dt                          -- list tables
SELECT * FROM hosts;
SELECT appointment_code, visitor_name, status FROM appointments;
\q                           -- quit
```

Connect to Redis for inspection:

```bash
docker compose exec redis redis-cli
KEYS *                       -- list all keys
GET session:kiosk-01:<uuid>  -- inspect a session
```

---

## Quick-Start Checklist

For an experienced developer who just cloned the repo:

```bash
# 1. Create env file
cp .env.example .env

# 2. Start the stack (builds image on first run)
docker compose up -d --build

# 3. Wait for startup — watch logs until "Robo ready"
docker compose logs -f reception-api

# 4. Seed the database
docker compose exec reception-api python seed.py

# 5. Confirm health
curl http://localhost:8000/health

# 6. Open frontend
# → http://localhost:8000/static/index.html
```

---

*End of Setup Guide*
