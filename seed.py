import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import settings
from app.db.models import Base, Host, Appointment, AvailabilitySlot, AppointmentStatus


async def seed():
    engine = create_async_engine(settings.database_url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as session:
        # Idempotency check
        result = await session.execute(select(Host).limit(1))
        if result.scalar():
            print("Already seeded — skipping.")
            return

        now = datetime.now(timezone.utc)
        today = now.replace(minute=0, second=0, microsecond=0)
        # Anchor slots to +1h from now so they are always in the future at test time
        base_today = today + timedelta(hours=1)
        base_tomorrow = today + timedelta(days=1, hours=1)

        # ── Hosts ──────────────────────────────────────────────────────────────
        # Four active hosts across three departments
        marcus = Host(
            id=uuid.uuid4(), name="Marcus Webb",
            email="marcus@robo.local", department="Engineering",
            notification_channel="marcus-webb",
        )
        sarah_lim = Host(
            id=uuid.uuid4(), name="Sarah Lim",
            email="sarah.lim@robo.local", department="Engineering",
            notification_channel="sarah-lim",
        )
        priya = Host(
            id=uuid.uuid4(), name="Priya Nair",
            email="priya@robo.local", department="HR",
            notification_channel="priya-nair",
        )
        david = Host(
            id=uuid.uuid4(), name="David Chen",
            email="david@robo.local", department="Management",
            notification_channel="david-chen",
        )
        # One inactive host — should NEVER appear in list_hosts results
        inactive = Host(
            id=uuid.uuid4(), name="Alex Turner",
            email="alex@robo.local", department="Engineering",
            notification_channel="alex-turner",
            is_active=False,
        )

        session.add_all([marcus, sarah_lim, priya, david, inactive])
        await session.flush()

        # ── Appointments ───────────────────────────────────────────────────────
        appointments = [

            # S1 — Happy path full check-in + acknowledge round-trip
            # Say: "Hi, I'm Sarah Chen, I have an appointment with Marcus"
            Appointment(
                appointment_code="APT001",
                visitor_name="Sarah Chen",
                host_id=marcus.id, room="204", floor=2,
                scheduled_at=base_today,
                status=AppointmentStatus.scheduled,
            ),

            # S2 — Code-based lookup (exact match, bypasses fuzzy)
            # Say: "My appointment code is APT002"
            Appointment(
                appointment_code="APT002",
                visitor_name="Liam Park",
                host_id=sarah_lim.id, room="Lab-B", floor=2,
                scheduled_at=base_today + timedelta(hours=1),
                status=AppointmentStatus.scheduled,
            ),

            # S3 — Fuzzy name match: visitor says "Jon Smith" (missing h, low match)
            # pg_trgm similarity "Jon Smith" vs "John Smith" ≈ 0.67 → confident match
            # Say: "Hi I'm Jon Smith" — should match and proceed to check-in
            Appointment(
                appointment_code="APT003",
                visitor_name="John Smith",
                host_id=priya.id, room="HR-01", floor=1,
                scheduled_at=base_today + timedelta(hours=2),
                status=AppointmentStatus.scheduled,
            ),

            # S4 — Low-confidence name → agent must ask to clarify
            # "Li" alone scores ~0.3 against "Liam Park" — below 0.45 threshold
            # Visitor says: "Hi I'm Li" → agent asks to spell full name
            # Then say full name "Emma Torres" → no match → agent says not found
            Appointment(
                appointment_code="APT004",
                visitor_name="Emma Torres",
                host_id=david.id, room="301", floor=3,
                scheduled_at=base_today + timedelta(hours=3),
                status=AppointmentStatus.scheduled,
            ),

            # S5 — Second full-cycle test after APT001 is used up
            # Say: "I'm James Okafor, here to see Priya"
            Appointment(
                appointment_code="APT005",
                visitor_name="James Okafor",
                host_id=priya.id, room="HR-02", floor=1,
                scheduled_at=base_today + timedelta(hours=4),
                status=AppointmentStatus.scheduled,
            ),

            # S6 — Hyphenated name (fuzzy stress test)
            # Say: "I'm Anne-Marie Dupont"
            Appointment(
                appointment_code="APT006",
                visitor_name="Anne-Marie Dupont",
                host_id=marcus.id, room="204", floor=2,
                scheduled_at=base_today + timedelta(hours=5),
                status=AppointmentStatus.scheduled,
            ),

            # S7 — Cancelled appointment (edge case — should NOT be found)
            # Say: "I'm Nina Osei" → lookup_appointment returns not found (status filter)
            Appointment(
                appointment_code="APT007",
                visitor_name="Nina Osei",
                host_id=marcus.id, room="204", floor=2,
                scheduled_at=base_today - timedelta(days=1),
                status=AppointmentStatus.cancelled,
            ),

            # S8 — Tomorrow appointment (availability check scenario)
            # For check_availability: "Is Marcus free tomorrow?"
            Appointment(
                appointment_code="APT008",
                visitor_name="Tom Bradley",
                host_id=marcus.id, room="204", floor=2,
                scheduled_at=base_tomorrow,
                status=AppointmentStatus.scheduled,
            ),
        ]
        session.add_all(appointments)

        # ── Availability slots ─────────────────────────────────────────────────
        # 4 slots per active host: 2 today (future), 2 tomorrow
        # One of Marcus's today slots is pre-booked to test mixed availability
        slots = []
        for host in [marcus, sarah_lim, priya, david]:
            for offset_hours in [1, 3]:
                # Today
                slots.append(AvailabilitySlot(
                    host_id=host.id,
                    slot_start=base_today + timedelta(hours=offset_hours),
                    slot_end=base_today + timedelta(hours=offset_hours + 1),
                    is_booked=False,
                ))
                # Tomorrow
                slots.append(AvailabilitySlot(
                    host_id=host.id,
                    slot_start=base_tomorrow + timedelta(hours=offset_hours),
                    slot_end=base_tomorrow + timedelta(hours=offset_hours + 1),
                    is_booked=False,
                ))

        # Mark one of Marcus's today slots as already booked
        # (tests that check_availability only shows free slots)
        slots[0].is_booked = True  # Marcus today +1h → booked

        # inactive host gets NO slots (confirms list_hosts excludes them)
        session.add_all(slots)

        await session.commit()
        print(
            f"Seeded: 5 active hosts (1 inactive), "
            f"{len(appointments)} appointments, "
            f"{len(slots)} availability slots"
        )


if __name__ == "__main__":
    asyncio.run(seed())
