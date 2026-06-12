# Logging — Quick Start (30 seconds)

## Start the App and See Logs

```bash
make up
```

You'll see:
```
[10:15:27] INFO  app.main : ✓ Robo ready — all systems operational!
[10:15:27] INFO  app.main : WebSocket: ws://localhost:8000/ws/voice/kiosk-01
```

## Test Voice Interaction

1. Open: http://localhost:8000/static/index.html
2. Click "Connect & Start"
3. Speak into microphone
4. Watch terminal for logs:

```
[10:20:15] INFO  app.voice.ws_handler : ✓ WebSocket connected: kiosk=kiosk-01
[10:20:21] INFO  app.voice.stt : STT: Transcribed (1.15s) → 'Hello'
[10:20:21] INFO  app.voice.tts : TTS: Synthesizing 3 sentence(s)
```

## View Logs in Separate Terminal

```bash
make logs
# or
docker compose logs -f robo-api
```

## Customize Log Levels

Edit `app/logging_config.py` line 20-40, change module levels, restart:

```bash
make reset
make up
```

## Key Logs to Expect

| What | Example Log |
|------|-------------|
| App started | `[10:15] INFO app.main : ✓ Robo ready` |
| WebSocket connected | `[10:20] INFO app.voice.ws_handler : ✓ WebSocket connected` |
| Voice detected | `[10:20] DEBUG app.voice.ws_handler : State: listening` |
| Speech recognized | `[10:21] INFO app.voice.stt : STT: Transcribed (1.15s)` |
| Response synthesized | `[10:21] INFO app.voice.tts : TTS: Synthesizing N sentence(s)` |

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No logs visible | Check `docker compose logs robo-api` |
| Torch warnings appear | Restart: `make reset` then `make up` |
| Too verbose | Change "app" level to INFO in app/logging_config.py |
| Too quiet | Change "app" level to DEBUG in app/logging_config.py |

## Documentation

- **Full Guide:** `docs/LOGGING_GUIDE.md`
- **Quick Reference:** `docs/LOGGING_REFERENCE.md`
- **Details:** `docs/LOGGING_SETUP_SUMMARY.md`

---

**That's it!** Logs should now be visible, organized, and not overridden by library logs.
