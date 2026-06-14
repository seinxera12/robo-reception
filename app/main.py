import logging
import os
from contextlib import asynccontextmanager
import asyncio

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import traceback

from app.config import settings
from app.db.session import engine
from app.api.health import router as health_router
from app.voice.ws_handler import router as ws_router
from app.logging_config import setup_logging, suppress_library_spam

# Setup logging FIRST before any other module imports
setup_logging()
suppress_library_spam()

logger = logging.getLogger(__name__)

from fastapi.staticfiles import StaticFiles


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 70)
    logger.info("Starting Robo Reception Assistant...")
    logger.info("=" * 70)

    try:
        # Migrations — run in a thread so the event loop stays free
        logger.info("Applying database migrations...")
        from alembic.config import Config
        from alembic import command

        def _run_migrations():
            alembic_cfg = Config("alembic.ini")
            command.upgrade(alembic_cfg, "head")

        await asyncio.to_thread(_run_migrations)
        logger.info("✓ Migrations applied")

        # Redis
        logger.info("Connecting to Redis...")
        app.state.redis = aioredis.from_url(
            settings.redis_url, decode_responses=True
        )
        await app.state.redis.ping()
        logger.info(f"✓ Redis connected ({settings.redis_url})")

        # STT — load and pre-warm Whisper
        logger.info("Initializing STT (Speech-to-Text)...")
        logger.info("  This may take 1-2 minutes on first run...")
        from app.voice.stt import load_stt_model
        try:
            app.state.stt_model = await asyncio.wait_for(
                asyncio.to_thread(load_stt_model),
                timeout=300  # 5 minutes timeout
            )
            logger.info("✓ STT ready")
        except asyncio.TimeoutError:
            logger.error("✗ STT model loading timed out (5 min)")
            raise

        # TTS — load and pre-warm Kokoro
        logger.info("Initializing TTS (Text-to-Speech)...")
        logger.info("  This may take 30-60 seconds on first run...")
        from app.voice.tts import load_tts_model
        try:
            await asyncio.wait_for(
                asyncio.to_thread(load_tts_model),
                timeout=300  # 5 minutes timeout
            )
            logger.info("✓ TTS ready")
        except asyncio.TimeoutError:
            logger.error("✗ TTS model loading timed out (5 min)")
            raise

        # ── Agent ─────────────────────────────────────────────────────────
        # Validate Groq API key presence
        if not settings.groq_api_key:
            logger.warning("⚠  GROQ_API_KEY not set — agent will fail on first utterance")
        else:
            logger.info("✓ Groq API key configured")

        # Import agent — triggers tool registration, surfaces any import errors at boot
        logger.info("Initializing agent and registering tools...")
        from app.agent.core import agent as _agent  # noqa: F401
        tool_names = list(_agent._function_toolset.tools.keys())
        logger.info(f"✓ Agent ready — tools: {tool_names}")

        logger.info("=" * 70)
        logger.info("✓ Robo ready — all systems operational!")
        logger.info("=" * 70)
        logger.info(f"Frontend: http://localhost:8000/static/index.html")
        logger.info(f"WebSocket: ws://localhost:8000/ws/voice/kiosk-01")
        logger.info(f"Health: http://localhost:8000/health")
        logger.info("=" * 70)
        logger.info("Waiting for connections... (Press CTRL+C to shut down)")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.exception(f"✗ Startup failed: {e}")
        logger.error("=" * 70)
        raise
    
    yield

    # Shutdown
    logger.info("=" * 70)
    logger.info("Shutting down Robo...")
    try:
        await app.state.redis.aclose()
        await engine.dispose()
        logger.info("✓ Robo shut down cleanly")
    except Exception as e:
        logger.exception(f"✗ Shutdown error: {e}")
    finally:
        logger.info("=" * 70)


app = FastAPI(title="Robo Reception Assistant", lifespan=lifespan)

app.include_router(health_router)
app.include_router(ws_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__}
    )


app.mount("/static", StaticFiles(directory="frontend"), name="static")