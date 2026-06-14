# app/agent/models.py
from typing import Any
from pydantic import BaseModel


# ── Tool Outputs ───────────────────────────────────────────────────────────

class AppointmentMatch(BaseModel):
    found: bool
    appointment_id: str | None = None
    appointment_code: str | None = None
    visitor_name: str | None = None
    host_name: str | None = None
    host_id: str | None = None
    room: str | None = None
    floor: int | None = None
    scheduled_at: str | None = None   # ISO string — LLM handles strings better than datetime
    status: str | None = None
    confidence: float = 0.0
    suggestions: list[str] = []       # alternate names if not found
    message: str = ""


class AvailabilitySlot(BaseModel):
    slot_start: str
    slot_end: str
    is_booked: bool


class AvailabilityResult(BaseModel):
    found: bool
    host_name: str | None = None
    host_id: str | None = None
    slots: list[AvailabilitySlot] = []
    message: str = ""


class InfoResult(BaseModel):
    found: bool
    query_type: str
    answer: str = ""


# ── Agent Dependencies (passed via RunContext) ─────────────────────────────

class RoboDeps(BaseModel):
    kiosk_id: str
    session_uuid: str
    visitor_name: str | None = None            # populated after successful lookup
    current_appointment_id: str | None = None  # populated after successful lookup
    redis: Any = None                          # injected from ws_handler for pub/sub events

    model_config = {"arbitrary_types_allowed": True}
