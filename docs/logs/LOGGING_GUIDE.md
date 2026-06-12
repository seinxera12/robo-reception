# Logging Configuration Guide

## Overview

Robo uses a centralized, hierarchical logging configuration that ensures all application logs are visible while suppressing verbose third-party library logs.

**Key Principle:** App modules log at DEBUG/INFO, third-party libraries are muted at WARNING level.

## Configuration Files

### Primary Configuration
- **File:** `app/logging_config.py`
- **Purpose:** Centralized logging setup, module-level filters, formatters
- **Imported by:** `app/main.py` at startup (before any other app code)

### Logging Levels by Module

| Module | Level | Notes |
|--------|-------|-------|
| `app` | DEBUG | All app modules catch everything |
| `app.main` | INFO | Startup/shutdown events |
| `app.voice.*` | DEBUG/INFO | Voice pipeline (VAD, STT, TTS) |
| `app.db.*` | INFO | Database operations |
| `app.api.*` | INFO | API endpoints |
| `app.session.*` | INFO | Session management |
| **Third-Party:** |
| `torch` | WARNING | PyTorch (heavy output suppressed) |
| `transformers` | WARNING | HuggingFace (error level via transformers.logging) |
| `huggingface_hub` | WARNING | Hub chatter (error level via SDK) |
| `sqlalchemy` | WARNING | SQL queries suppressed |
| `asyncpg` | WARNING | DB driver |
| `redis` | WARNING | Redis client |
| `httpx` | WARNING | HTTP client |
| `uvicorn` | INFO | Server startup messages |

## Log Format

```
[HH:MM:SS] LEVEL logger_name : message
```

### Examples
```
[10:15:30] INFO  app.main : ✓ Migrations applied
[10:15:31] DEBUG app.voice.vad : Loading Silero VAD model from torch hub...
[10:15:35] INFO  app.voice.stt : ✓ STT model ready (5.2s)
[10:15:38] INFO  app.voice.ws_handler : ✓ WebSocket connected: kiosk=kiosk-01
[10:15:40] INFO  app.voice.vad : VAD: Utterance complete (12 chunks, 0.4s)
[10:15:41] INFO  app.voice.stt : STT: Transcribed (1.23s) → 'Hello I have an appointment'
[10:15:42] INFO  app.voice.tts : TTS: Synthesizing 3 sentence(s) (124 chars)
```

## Startup Logging

When you start the app with `make up`, you'll see:

```
[10:15:20] INFO  app.main : ======================================================================
[10:15:20] INFO  app.main : Logging configured — app modules at DEBUG/INFO, third-party at WARNING
[10:15:20] INFO  app.main : ======================================================================
[10:15:20] INFO  app.main : ======================================================================
[10:15:20] INFO  app.main : Starting Robo Reception Assistant...
[10:15:20] INFO  app.main : ======================================================================
[10:15:20] INFO  app.main : Applying database migrations...
[10:15:20] INFO  app.main : ✓ Migrations applied
[10:15:20] INFO  app.main : Connecting to Redis...
[10:15:20] INFO  app.main : ✓ Redis connected (redis://redis:6379/0)
[10:15:20] INFO  app.main : Initializing STT (Speech-to-Text)...
[10:15:20] DEBUG app.voice.stt : Loading STT model (Faster-Whisper small.en, int8)...
[10:15:25] INFO  app.voice.stt : ✓ STT model ready (5.1s)
[10:15:25] INFO  app.main : Initializing TTS (Text-to-Speech)...
[10:15:25] DEBUG app.voice.tts : Loading TTS model (Kokoro American English)...
[10:15:27] INFO  app.voice.tts : ✓ TTS model ready (2.3s)
[10:15:27] INFO  app.main : ======================================================================
[10:15:27] INFO  app.main : ✓ Robo ready — all systems operational!
[10:15:27] INFO  app.main : ======================================================================
[10:15:27] INFO  app.main : Frontend: http://localhost:8000/static/index.html
[10:15:27] INFO  app.main : WebSocket: ws://localhost:8000/ws/voice/kiosk-01
[10:15:27] INFO  app.main : ======================================================================
```

## Real-Time Session Logging

When a visitor uses the kiosk, you'll see:

```
[10:20:15] INFO  app.voice.ws_handler : ✓ WebSocket connected: kiosk=kiosk-01
[10:20:15] DEBUG app.voice.ws_handler :   Session created: 550e8400-e29b-41d4-a716-446655440000
[10:20:15] DEBUG app.voice.ws_handler :   VAD processor initialized
[10:20:15] INFO  app.voice.ws_handler :   Entering voice loop...
[10:20:15] DEBUG app.voice.ws_handler :   State: idle

(visitor speaks for ~2 seconds)

[10:20:18] DEBUG app.voice.ws_handler :   State: listening
[10:20:20] INFO  app.voice.vad : VAD: Utterance complete (24 chunks, 0.8s)
[10:20:20] INFO  app.voice.ws_handler :   Processing utterance...
[10:20:20] DEBUG app.voice.ws_handler :   State: thinking
[10:20:21] INFO  app.voice.stt : STT: Transcribed (1.15s) → 'Hi I have an appointment with Marcus'
[10:20:21] INFO  app.voice.ws_handler :   Transcript sent: 'Hi I have an appointment with Marcus'
[10:20:21] INFO  app.voice.ws_handler :   Response sent: 'Thank you, I heard you. I am Robo...'
[10:20:21] INFO  app.voice.ws_handler :   Streaming TTS audio...
[10:20:21] DEBUG app.voice.ws_handler :   State: speaking
[10:20:21] INFO  app.voice.tts : TTS: Synthesizing 4 sentence(s) (142 chars)
[10:20:21] DEBUG app.voice.tts : TTS: Sentence 1/4 (0.28s) → 3584 bytes
[10:20:22] DEBUG app.voice.tts : TTS: Sentence 2/4 (0.31s) → 4096 bytes
[10:20:22] DEBUG app.voice.tts : TTS: Sentence 3/4 (0.25s) → 2944 bytes
[10:20:22] DEBUG app.voice.tts : TTS: Sentence 4/4 (0.18s) → 2048 bytes
[10:20:22] INFO  app.voice.ws_handler :   TTS complete (4 chunks)
[10:20:23] DEBUG app.voice.ws_handler :   State: idle
[10:20:30] INFO  app.voice.ws_handler : ✓ WebSocket disconnected: kiosk=kiosk-01
[10:20:30] DEBUG app.voice.ws_handler :   Session cleaned up: 550e8400-e29b-41d4-a716-446655440000
```

## Customizing Logging

### Change a Module's Log Level

Edit `app/logging_config.py`:

```python
LOG_LEVELS = {
    "app.voice.stt": logging.DEBUG,      # Make STT more verbose
    "sqlalchemy.engine": logging.INFO,   # See SQL queries
    ...
}
```

Then restart:
```bash
make reset
make up
```

### Add Logging to Your Code

```python
import logging

logger = logging.getLogger(__name__)

# In functions:
logger.debug("Debug message (only shown if level is DEBUG)")
logger.info("Info message (always shown for app modules)")
logger.warning("Warning message (suppressed for most app modules, shown for third-party)")
logger.error("Error message (always shown)")
```

### Suppress Additional Libraries

In `app/logging_config.py`, the `suppress_library_spam()` function handles special cases:

```python
def suppress_library_spam() -> None:
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    # Add more as needed...
```

## Troubleshooting

### "I don't see any logs"
1. Check that `setup_logging()` was called in `app/main.py` (it should be line 16)
2. Check that logs go to stderr, not stdout: `make logs` should show them
3. Verify the container is actually running: `docker compose ps`

### "I see too many library logs"
1. Add the library name to `LOG_LEVELS` in `logging_config.py` with `logging.WARNING`
2. Or handle it specially in `suppress_library_spam()`

### "I need to see SQL queries"
1. Change `sqlalchemy` level to INFO in `LOG_LEVELS`
2. **Warning:** This will be very verbose with every query, only for debugging

### "Torch/PyTorch logs are overwhelming"
1. They should already be suppressed at WARNING level
2. If not, check that `setup_logging()` is called before importing torch modules
3. Try adding to `suppress_library_spam()`:
   ```python
   import torch
   torch.set_printoptions(threshold=10000)
   os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"
   ```

## Architecture

```
app/main.py (line 16)
  ↓
app/logging_config.setup_logging()
  ├─ Create console handler (stderr)
  ├─ Set root logger to DEBUG
  ├─ Configure per-module levels from LOG_LEVELS dict
  └─ Log startup message
  ↓
app/logging_config.suppress_library_spam()
  ├─ Special handling for transformers
  ├─ Special handling for huggingface_hub
  └─ Override specific submodules

All subsequent app module imports and logging use this configuration.
```

## Performance Impact

Logging has minimal overhead:
- **Disabled logs** (DEBUG when level is INFO) cost ~1-2µs per call
- **Enabled logs** cost ~10-50µs depending on message complexity
- **Third-party logs** are pre-filtered at handler level (no computation waste)

---

**See Also:**
- `docs/PROJECT_DISCOVERY.md` — Overall project architecture
- `app/logging_config.py` — Source code for logging setup
