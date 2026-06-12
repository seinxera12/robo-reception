from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import logging

from app.db.session import get_session
import app.voice.stt as stt_module
import app.voice.tts as tts_module

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
async def health(request: Request, session: AsyncSession = Depends(get_session)):
    # Postgres
    try:
        await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    # Redis
    try:
        await request.app.state.redis.ping()
        redis_status = "ok"
    except Exception as e:
        redis_status = f"error: {e}"
        
    # STT — check the module-level _model variable is actually loaded
    stt_status = "ok" if stt_module._model is not None else "not loaded"

    # TTS — same pattern
    tts_status = "ok" if tts_module._pipeline is not None else "not loaded"

    all_ready = db_status == "ok" and redis_status == "ok" and stt_status == "ok" and tts_status == "ok"

    return {
        "db": db_status,
        "redis": redis_status,
        "llm": "pending",
        "stt": stt_status,
        "tts": tts_status,
        "all_ready": all_ready,
    }

@router.get("/ping")
async def ping():
    return {"pong": True}