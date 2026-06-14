# app/tools/notifications.py
import json
import logging

import httpx
from pydantic import BaseModel
from pydantic_ai import RunContext
from sqlalchemy import select

from app.agent.core import agent
from app.agent.models import RoboDeps
from app.config import settings
from app.db.models import Appointment, Host
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class NotifyResult(BaseModel):
    sent: bool
    channel: str | None = None
    message: str = ""


@agent.tool
async def notify_host(
    ctx: RunContext[RoboDeps],
    host_id: str,
    visitor_name: str,
    appointment_id: str,
) -> NotifyResult:
    """
    Send a push notification to the host via ntfy.
    The notification includes an acknowledgement link the host can tap.
    Call this after update_checkin_status succeeds.
    """
    logger.info(f"Tool: notify_host(host_id={host_id}, visitor={visitor_name})")

    async with AsyncSessionLocal() as session:
        # ── Fetch host ────────────────────────────────────────────────────
        host_result = await session.execute(
            select(Host).where(Host.id == host_id)
        )
        host = host_result.scalar_one_or_none()

        if not host:
            return NotifyResult(sent=False, message=f"Host {host_id} not found.")

        # ── Build URLs ────────────────────────────────────────────────────
        ack_url = f"{settings.base_url}/acknowledge/{appointment_id}"
        topic = host.notification_channel
        ntfy_url = f"{settings.ntfy_host}/{topic}"

        # ── Build ntfy payload ────────────────────────────────────────────
        payload = {
            "topic": topic,
            "title": f"Visitor arrived: {visitor_name}",
            "message": f"{visitor_name} is at reception for you.",
            "actions": [
                {
                    "action": "view",
                    "label": "I'm on my way ✓",
                    "url": ack_url,
                    "clear": True,
                }
            ],
            "priority": "high",
            "tags": ["bell", "office"],
        }

        # ── Send notification ─────────────────────────────────────────────
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(ntfy_url, json=payload)
                response.raise_for_status()

        except httpx.HTTPError as e:
            logger.error(f"ntfy send failed: {e}")
            return NotifyResult(
                sent=False,
                message=f"Failed to notify host: {e}"
            )

        # ── Mark notification sent in DB ──────────────────────────────────
        appt_result = await session.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appt = appt_result.scalar_one_or_none()
        if appt:
            appt.notification_sent = True
            await session.commit()

        logger.info(f"  notify_host: → {host.name} via ntfy/{topic}")

        # ── Publish event for browser badge ───────────────────────────────
        if ctx.deps.redis is not None:
            await ctx.deps.redis.publish("robo:events", json.dumps({
                "type": "notification_sent",
                "appointment_id": appointment_id,
                "host_name": host.name,
            }))

        return NotifyResult(
            sent=True,
            channel=topic,
            message=f"Notification sent to {host.name}."
        )
