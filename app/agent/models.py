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


# ── Check-in Stage Tracking ────────────────────────────────────────────────

class CheckinStage(str):
    """
    Tracks which step of the check-in flow the current session is at.
    Used by the system prompt to inject explicit instructions for the next action.

    Stages (in order):
      idle          → no appointment found yet; greet and ask for name/code
      appointment_found → lookup succeeded; ask visitor to confirm details
      confirmed     → visitor confirmed; ask permission to check in
      checked_in    → update_checkin_status succeeded; ask permission to notify host
      notified      → notify_host succeeded; offer directions and close out
    """
    IDLE = "idle"
    APPOINTMENT_FOUND = "appointment_found"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    NOTIFIED = "notified"


# ── Agent Dependencies (passed via RunContext) ─────────────────────────────

class RoboDeps(BaseModel):
    kiosk_id: str
    session_uuid: str
    visitor_name: str | None = None            # populated after successful lookup
    current_appointment_id: str | None = None  # populated after successful lookup
    host_id: str | None = None                 # populated after successful lookup
    checkin_stage: str = CheckinStage.IDLE     # tracks which step the flow is at
    redis: Any = None                          # injected from ws_handler for pub/sub events

    model_config = {"arbitrary_types_allowed": True}
