# app/tools/appointments.py
import json
import logging
from datetime import date as Date,datetime, timezone
from sqlalchemy import text, select
from pydantic import BaseModel
from pydantic_ai import RunContext

from app.agent.core import agent
from app.agent.models import RoboDeps, AppointmentMatch, AvailabilityResult, AvailabilitySlot
from app.db.models import Appointment, Host, AppointmentStatus
from app.db.session import AsyncSessionLocal
from app.session.manager import SessionManager

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────

async def _persist_deps(ctx: RunContext[RoboDeps]) -> None:
    """
    Write the mutable fields of ctx.deps back to Redis so the next turn
    picks up the updated stage, visitor_name, and appointment/host IDs.
    """
    if ctx.deps.redis is None:
        return
    sm = SessionManager(ctx.deps.redis)
    try:
        await sm.update(ctx.deps.kiosk_id, ctx.deps.session_uuid, {
            "visitor_name": ctx.deps.visitor_name,
            "current_appointment_id": ctx.deps.current_appointment_id,
            "host_id": ctx.deps.host_id,
            "checkin_stage": ctx.deps.checkin_stage,
        })
    except Exception as exc:
        logger.warning(f"  _persist_deps: failed to write stage — {exc}")


# ── Tool 1: lookup_appointment ─────────────────────────────────────────────

@agent.tool
async def lookup_appointment(
    ctx: RunContext[RoboDeps],
    visitor_name: str | None = None,
    appointment_code: str | None = None,
) -> AppointmentMatch:
    """
    Look up a visitor's appointment by name or appointment code.
    Use visitor_name for name-based lookup, appointment_code if the visitor provides a code.
    Always queries live — never cached.
    Returns appointment details on match, or suggestions for clarification on partial match.
    """
    logger.info(f"Tool: lookup_appointment(name={visitor_name!r}, code={appointment_code!r})")

    async with AsyncSessionLocal() as session:

        # ── Code-based lookup (exact match) ───────────────────────────────
        if appointment_code:
            result = await session.execute(
                select(Appointment, Host)
                .join(Host, Appointment.host_id == Host.id)
                .where(Appointment.appointment_code == appointment_code.upper())
                .where(Appointment.status == AppointmentStatus.scheduled)
            )
            row = result.first()
            if row:
                appt, host = row
                match = _appointment_to_match(appt, host, confidence=1.0)
                # Advance stage so the prompt asks for confirmation next
                ctx.deps.visitor_name = appt.visitor_name
                ctx.deps.current_appointment_id = str(appt.id)
                ctx.deps.host_id = str(appt.host_id)
                ctx.deps.checkin_stage = "appointment_found"
                await _persist_deps(ctx)
                return match
            return AppointmentMatch(
                found=False,
                message=f"No scheduled appointment found with code '{appointment_code}'."
            )
        # ── Name-based fuzzy lookup (pg_trgm similarity) ──────────────────
        if not visitor_name:
            return AppointmentMatch(
                found=False,
                message="Please provide your name or appointment code."
            )

        fuzzy_query = text("""
            SELECT
                a.id,
                a.appointment_code,
                a.visitor_name,
                a.room,
                a.floor,
                a.scheduled_at,
                a.status,
                a.host_id,
                h.name  AS host_name,
                similarity(a.visitor_name, :name) AS score
            FROM appointments a
            JOIN hosts h ON a.host_id = h.id
            WHERE
                a.status = 'scheduled'
                AND similarity(a.visitor_name, :name) > 0.3
            ORDER BY score DESC
            LIMIT 5
        """)

        result = await session.execute(fuzzy_query, {"name": visitor_name})
        rows = result.fetchall()

        if not rows:
            return AppointmentMatch(
                found=False,
                suggestions=[],
                message=f"No appointment found for '{visitor_name}'."
            )

        best = rows[0]
        confidence = float(best.score)

        if confidence >= 0.45:
            logger.info(
                f"  lookup: matched '{best.visitor_name}' "
                f"conf={confidence:.2f} host={best.host_name} room={best.room}"
            )
            # Advance stage so the prompt knows to ask for confirmation next
            ctx.deps.visitor_name = best.visitor_name
            ctx.deps.current_appointment_id = str(best.id)
            ctx.deps.host_id = str(best.host_id)
            ctx.deps.checkin_stage = "appointment_found"
            await _persist_deps(ctx)
            return AppointmentMatch(
                found=True,
                appointment_id=str(best.id),
                appointment_code=best.appointment_code,
                visitor_name=best.visitor_name,
                host_name=best.host_name,
                host_id=str(best.host_id),
                room=best.room,
                floor=best.floor,
                scheduled_at=best.scheduled_at.isoformat(),
                status=best.status,
                confidence=confidence,
            )

        # Low confidence — return candidate names so the agent can ask to clarify
        suggestions = [r.visitor_name for r in rows if float(r.score) > 0.2]
        logger.info(
            f"  lookup: low confidence ({confidence:.2f}) for {visitor_name!r}"
            f" — suggestions: {suggestions}"
        )
        return AppointmentMatch(
            found=False,
            confidence=confidence,
            suggestions=suggestions,
            message=f"Could not find a confident match for '{visitor_name}'."
        )


# ── Tool 2: check_availability ─────────────────────────────────────────────

@agent.tool
async def check_availability(
    ctx: RunContext[RoboDeps],
    host_name: str,
    date: str,  # ISO date string e.g. "2025-01-15"
) -> AvailabilityResult:
    """
    Check available appointment slots for a host on a given date.
    host_name is fuzzy-matched so partial names work.
    date must be an ISO date string (YYYY-MM-DD).
    Returns only the open (not yet booked) slots.
    """
    logger.info(f"Tool: check_availability(host={host_name!r}, date={date!r})")

    # TODO Day 4: check Redis cache before querying DB

    async with AsyncSessionLocal() as session:

        # Fuzzy-match host name against active hosts
        host_query = text("""
            SELECT id, name
            FROM hosts
            WHERE is_active = true
              AND similarity(name, :name) > 0.4
            ORDER BY similarity(name, :name) DESC
            LIMIT 1
        """)
        host_result = await session.execute(host_query, {"name": host_name})
        host_row = host_result.first()

        if not host_row:
            return AvailabilityResult(
                found=False,
                message=f"Could not find an active host named '{host_name}'."
            )

        host_id = str(host_row.id)
        resolved_name = host_row.name
        query_date = Date.fromisoformat(date)
        # Query all slots for this host on the given date (both booked and free)
        slots_query = text("""
            SELECT slot_start, slot_end, is_booked
            FROM availability_slots
            WHERE host_id = :host_id
              AND slot_start::date = :date
            ORDER BY slot_start
        """)
        slots_result = await session.execute(
            slots_query, {"host_id": host_id, "date": query_date}
        )
        slot_rows = slots_result.fetchall()

        # Filter to open slots in Python — gives us flexibility without a second query
        open_slots = [
            AvailabilitySlot(
                slot_start=row.slot_start.isoformat(),
                slot_end=row.slot_end.isoformat(),
                is_booked=row.is_booked,
            )
            for row in slot_rows
            if not row.is_booked
        ]

        logger.info(
            f"  availability: '{resolved_name}' → {len(open_slots)} open slot(s) on {date}"
        )

        return AvailabilityResult(
            found=True,
            host_name=resolved_name,
            host_id=host_id,
            slots=open_slots,
            message=f"{resolved_name} has {len(open_slots)} open slot(s) on {date}.",
        )


# ── Tool 3: confirm_appointment ────────────────────────────────────────────

class ConfirmResult(BaseModel):
    confirmed: bool
    appointment_id: str | None = None
    message: str = ""


@agent.tool
async def confirm_appointment(
    ctx: RunContext[RoboDeps],
    appointment_id: str,
) -> ConfirmResult:
    """
    Record that the visitor has verbally confirmed their appointment details.
    Call this ONLY after presenting the appointment details and the visitor
    says "yes", "correct", "that's me", or similar affirmation.
    Do NOT call this speculatively — wait for the visitor's confirmation.
    After this returns confirmed=true, ask the visitor if they'd like to check in.
    """
    logger.info(f"Tool: confirm_appointment(appointment_id={appointment_id})")

    ctx.deps.checkin_stage = "confirmed"
    await _persist_deps(ctx)

    logger.info(f"  confirm: ✓ appointment {appointment_id[:8]}… → confirmed")
    return ConfirmResult(
        confirmed=True,
        appointment_id=appointment_id,
        message="Appointment confirmed by visitor.",
    )


# ── Tool 4: update_checkin_status ─────────────────────────────────────────

class CheckinResult(BaseModel):
    success: bool
    appointment_id: str | None = None
    message: str = ""


@agent.tool
async def update_checkin_status(
    ctx: RunContext[RoboDeps],
    appointment_id: str,
) -> CheckinResult:
    """
    Mark a visitor as checked in. Call this after lookup_appointment succeeds
    and the visitor has confirmed their details.
    Sets status to checked_in and records the check-in timestamp.
    """
    logger.info(f"Tool: update_checkin_status(appointment_id={appointment_id})")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appt = result.scalar_one_or_none()

        if not appt:
            return CheckinResult(
                success=False,
                message=f"Appointment {appointment_id} not found."
            )

        if appt.status == AppointmentStatus.checked_in:
            return CheckinResult(
                success=True,
                appointment_id=appointment_id,
                message="Visitor was already checked in."
            )

        appt.status = AppointmentStatus.checked_in
        appt.check_in_at = datetime.now(timezone.utc)
        await session.commit()

        logger.info(f"  checkin: ✓ appointment {appointment_id[:8]}… → checked_in")

        # Advance stage so the prompt asks for host notification permission next
        ctx.deps.checkin_stage = "checked_in"
        await _persist_deps(ctx)

        # Publish event so the WebSocket listener can update the browser badge
        if ctx.deps.redis is not None:
            _payload = json.dumps({
                "type": "checkin_complete",
                "appointment_id": appointment_id,
                "session_uuid": ctx.deps.session_uuid,
            })
            _receivers = await ctx.deps.redis.publish("robo:events", _payload)
            logger.info(
                f"  [DIAG] publish checkin_complete → robo:events "
                f"receivers={_receivers} (0 = no active subscriber)"
            )
        else:
            logger.warning("  [DIAG] publish checkin_complete SKIPPED — ctx.deps.redis is None")

        return CheckinResult(
            success=True,
            appointment_id=appointment_id,
            message="Visitor successfully checked in."
        )


# ── Helpers ────────────────────────────────────────────────────────────────

def _appointment_to_match(appt: Appointment, host: Host, confidence: float) -> AppointmentMatch:
    return AppointmentMatch(
        found=True,
        appointment_id=str(appt.id),
        appointment_code=appt.appointment_code,
        visitor_name=appt.visitor_name,
        host_name=host.name,
        host_id=str(appt.host_id),
        room=appt.room,
        floor=appt.floor,
        scheduled_at=appt.scheduled_at.isoformat(),
        status=appt.status.value,
        confidence=confidence,
    )
