import uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum as SAEnum
from datetime import datetime
import enum

class Base(DeclarativeBase):
    pass

class AppointmentStatus(enum.Enum):
    scheduled = "scheduled"
    checked_in = "checked_in"
    cancelled = "cancelled"

class Host(Base):
    __tablename__ = "hosts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default = uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    department : Mapped[str] = mapped_column(String(100))
    notification_channel: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default = True)

class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default = uuid.uuid4)
    appointment_code: Mapped[str] = mapped_column(String(16), unique=True)
    visitor_name: Mapped[str] = mapped_column(String(200))
    host_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hosts.id"))
    room: Mapped[str] = mapped_column(String(50))
    floor: Mapped[int]
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[AppointmentStatus] = mapped_column(
        SAEnum(AppointmentStatus), default=AppointmentStatus.scheduled
    )
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    notification_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)

class AvailabilitySlot(Base):
    __tablename__ = "availability_slots"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    host_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hosts.id"))
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    slot_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_booked: Mapped[bool] = mapped_column(Boolean, default=False)
    
