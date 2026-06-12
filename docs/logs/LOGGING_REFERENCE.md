# Logging Reference — Quick Cheat Sheet

## What You'll See in Terminal

### Startup
```
[10:15:27] INFO  app.main : ✓ Robo ready — all systems operational!
[10:15:27] INFO  app.main : WebSocket: ws://localhost:8000/ws/voice/kiosk-01
```

### Visitor Interaction
```
[10:20:15] INFO  app.voice.ws_handler : ✓ WebSocket connected: kiosk=kiosk-01
[10:20:21] INFO  app.voice.stt : STT: Transcribed (1.15s) → 'Hi I have an appointment'
[10:20:21] INFO  app.voice.tts : TTS: Synthesizing 4 sentence(s) (142 chars)
[10:20:30] INFO  app.voice.ws_handler : ✓ WebSocket disconnected: kiosk=kiosk-01
```

### Health Check
```
[10:25:00] INFO  app.api.health : Health check OK (db=ok, redis=ok, stt=ok, tts=ok)
```

## Log Levels

| Level | Visibility | Use Case |
|-------|-----------|----------|
| DEBUG | App only | Detailed tracing (connection setup, state changes) |
| INFO | App + uvicorn | Important events (startup, connections, transcriptions) |
| WARNING | All modules | Unusual but not critical (slow requests, retries) |
| ERROR | All modules | Failures (exceptions, crashes) |

## Key Log Sources

| Source | Examples |
|--------|----------|
| `app.main` | Startup, shutdown, database migrations |
| `app.voice.ws_handler` | WebSocket connects/disconnects, state transitions |
| `app.voice.vad` | Voice detection, utterance boundaries |
| `app.voice.stt` | Transcription results and latency |
| `app.voice.tts` | Synthesis progress, audio chunks |
| `app.session.manager` | Session creation/deletion |
| `app.api.health` | Service readiness checks |

## Common Patterns

### To add logging to your code:
```python
import logging
logger = logging.getLogger(__name__)

logger.info("User action completed")  # Always visible
logger.debug("Internal state: x=5")   # Only when debugging
logger.warning("Unexpected behavior") # Shows for both app and libraries
```

### To suppress a noisy library:
1. Edit `app/logging_config.py`
2. Find `LOG_LEVELS` dict
3. Add or update: `"library_name": logging.WARNING`
4. Restart app

### To see all SQL queries:
1. Edit `app/logging_config.py`
2. Change `"sqlalchemy.engine": logging.DEBUG`
3. **Warning:** Very verbose!

## Performance Tips

- **DEBUG logs** are cheap if not printed (~2µs each)
- **INFO logs** should describe real events, not every loop iteration
- **Avoid** string formatting in disabled logs:
  ```python
  # ❌ Bad (formatted even if not printed)
  logger.debug(f"Value is {expensive_function()}")
  
  # ✅ Good (formatted only if DEBUG is on)
  if logger.isEnabledFor(logging.DEBUG):
      logger.debug(f"Value is {expensive_function()}")
  ```

## Example Output Analysis

```
[10:20:21] INFO  app.voice.stt : STT: Transcribed (1.15s) → 'Hello'
           └─ timestamp  └─ level └─ module           └─ message
                                    └─ logger name
```

**Read as:** "At 10:20:21, the STT module logged an INFO message showing that transcription took 1.15 seconds and produced 'Hello'"

---

**See:** `docs/LOGGING_GUIDE.md` for detailed configuration options
