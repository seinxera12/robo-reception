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
        today_2pm = now.replace(hour=14, minute=0, second=0, microsecond=0)

        # ── Hosts ──────────────────────────────────────────────
        marcus = Host(
            id=uuid.uuid4(), name="Marcus Webb",
            email="marcus@robo.local", department="Engineering",
            notification_channel="marcus-webb",
        )
        sarah_h = Host(
            id=uuid.uuid4(), name="Sarah Lim",
            email="sarah@robo.local", department="Engineering",
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

        session.add_all([marcus, sarah_h, priya, david])
        await session.flush()  # get IDs without committing

        # ── Appointments ───────────────────────────────────────
        appointments = [
            # Scenario 1: standard check-in
            Appointment(
                appointment_code="APT001",
                visitor_name="Sarah Chen",
                host_id=marcus.id, room="204", floor=2,
                scheduled_at=today_2pm,
                status=AppointmentStatus.scheduled,
            ),
            # Scenario 3: name mismatch (seeded as Smith, visitor says Smyth)
            Appointment(
                appointment_code="APT002",
                visitor_name="John Smith",
                host_id=priya.id, room="HR-01", floor=1,
                scheduled_at=today_2pm + timedelta(hours=1),
                status=AppointmentStatus.scheduled,
            ),
            # Scenario 5: host acknowledgement test
            Appointment(
                appointment_code="APT003",
                visitor_name="Emma Torres",
                host_id=david.id, room="301", floor=3,
                scheduled_at=today_2pm + timedelta(hours=2),
                status=AppointmentStatus.scheduled,
            ),
            # Tomorrow appointments (availability check scenario)
            Appointment(
                appointment_code="APT004",
                visitor_name="Liam Park",
                host_id=sarah_h.id, room="Lab-B", floor=2,
                scheduled_at=today_2pm + timedelta(days=1),
                status=AppointmentStatus.scheduled,
            ),
            # Cancelled — edge case
            Appointment(
                appointment_code="APT005",
                visitor_name="Nina Osei",
                host_id=marcus.id, room="204", floor=2,
                scheduled_at=today_2pm - timedelta(days=1),
                status=AppointmentStatus.cancelled,
            ),
        ]
        session.add_all(appointments)

        # ── Availability slots (3 per host, today + tomorrow) ──
        slots = []
        for host in [marcus, sarah_h, priya, david]:
            for day_offset in [0, 1]:
                base = today_2pm + timedelta(days=day_offset)
                for hour_offset in [0, 2, 4]:
                    slots.append(AvailabilitySlot(
                        host_id=host.id,
                        slot_start=base + timedelta(hours=hour_offset),
                        slot_end=base + timedelta(hours=hour_offset + 1),
                        is_booked=False,
                    ))
        session.add_all(slots)

        await session.commit()
        print(f"Seeded: 4 hosts, {len(appointments)} appointments, {len(slots)} slots")


if __name__ == "__main__":
    asyncio.run(seed())