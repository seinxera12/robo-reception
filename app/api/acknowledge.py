# app/api/acknowledge.py
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.db.models import Appointment, Host
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/acknowledge/{appointment_id}", response_class=HTMLResponse)
async def acknowledge(appointment_id: str, request: Request):
    """
    Host taps this link from the ntfy push notification.
    Sets notification_acknowledged = True and broadcasts a Redis event
    so the kiosk WebSocket can update the browser UI in real time.
    """
    logger.info(f"Acknowledge request: appointment_id={appointment_id}")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Appointment, Host)
            .join(Host, Appointment.host_id == Host.id)
            .where(Appointment.id == appointment_id)
        )
        row = result.first()

        if not row:
            return HTMLResponse(
                content="<h2>Appointment not found.</h2>",
                status_code=404,
            )

        appt, host = row

        # Idempotent — safe to tap the link multiple times
        if not appt.notification_acknowledged:
            appt.notification_acknowledged = True
            await session.commit()
            logger.info(f"✓ Acknowledged: {appt.visitor_name} → {host.name}")

        # Publish Redis event — the kiosk WebSocket listener receives this
        # and pushes a ui_update to the browser within milliseconds.
        redis = request.app.state.redis
        event = json.dumps({
            "type": "host_acknowledged",
            "appointment_id": appointment_id,
            "visitor_name": appt.visitor_name,
            "host_name": host.name,
        })
        receivers = await redis.publish("robo:events", event)
        logger.info(
            f"Redis event published: host_acknowledged for {appointment_id} "
            f"receivers={receivers} (0 = kiosk not subscribed or WebSocket disconnected)"
        )

        # Friendly confirmation page shown on the host's phone
        return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>On my way!</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            background: #f0fdf4;
        }}
        .card {{
            text-align: center;
            padding: 2.5rem 2rem;
            background: white;
            border-radius: 1rem;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
            max-width: 340px;
            width: 90%;
        }}
        .check {{
            font-size: 4rem;
            line-height: 1;
            margin-bottom: 1rem;
        }}
        h2 {{
            color: #16a34a;
            font-size: 1.6rem;
            margin-bottom: 0.75rem;
        }}
        p {{
            color: #6b7280;
            font-size: 1rem;
            line-height: 1.5;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="check">✓</div>
        <h2>On my way!</h2>
        <p>{host.name} is heading to reception to meet {appt.visitor_name}.</p>
    </div>
</body>
</html>""")
