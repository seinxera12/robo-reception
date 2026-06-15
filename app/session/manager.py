import asyncio
import uuid
import json
import logging
from datetime import datetime, timezone

from redis.exceptions import WatchError

from app.config import settings

logger = logging.getLogger(__name__)

SESSION_TTL = 1800  # 30 minutes


class SessionManager:
    def __init__(self, redis_client):
        self.redis = redis_client

    def _key(self, kiosk_id: str, session_uuid: str) -> str:
        return f"session:{kiosk_id}:{session_uuid}"

    async def create(self, kiosk_id: str) -> str:
        session_uuid = str(uuid.uuid4())
        key = self._key(kiosk_id, session_uuid)

        data = {
            "kiosk_id": kiosk_id,
            "session_uuid": session_uuid,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "visitor_name": None,
            "current_appointment_id": None,
            "host_id": None,
            "checkin_stage": "idle",
            "conversation_history": [],
        }

        await self.redis.setex(key, SESSION_TTL, json.dumps(data))
        logger.debug(f"Session created: {key}")
        return session_uuid

    async def get(self, kiosk_id: str, session_uuid: str) -> dict | None:
        key = self._key(kiosk_id, session_uuid)
        raw = await self.redis.get(key)
        return json.loads(raw) if raw else None

    async def update(self, kiosk_id: str, session_uuid: str, updates: dict, retries: int = 3):
        key = self._key(kiosk_id, session_uuid)
        for attempt in range(retries):
            async with self.redis.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    raw = await pipe.get(key)
                    data = json.loads(raw) if raw else {}
                    data.update(updates)
                    pipe.multi()
                    pipe.setex(key, SESSION_TTL, json.dumps(data))
                    await pipe.execute()
                    return
                except WatchError:
                    if attempt == retries - 1:
                        logger.warning(
                            f"SessionManager.update: WatchError after {retries} retries for {key}"
                        )
                        raise
                    await asyncio.sleep(0.01 * (attempt + 1))

    async def delete(self, kiosk_id: str, session_uuid: str):
        key = self._key(kiosk_id, session_uuid)
        await self.redis.delete(key)
        logger.info(f"Session deleted: {key}")