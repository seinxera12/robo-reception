# app/tools/hosts.py
import logging
from datetime import datetime, timezone, timedelta

from pydantic import BaseModel
from pydantic_ai import RunContext
from sqlalchemy import text

from app.agent.core import agent
from app.agent.models import RoboDeps
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class HostInfo(BaseModel):
    host_id: str
    name: str
    department: str
    next_available_slot: str | None = None


class HostListResult(BaseModel):
    found: bool
    hosts: list[HostInfo] = []
    message: str = ""


@agent.tool
async def list_hosts(
    ctx: RunContext[RoboDeps],
    department: str | None = None,
) -> HostListResult:
    """
    List active staff members, optionally filtered by department.
    Returns each host with their next available slot today or within 48 hours.
    Use this for walk-in visitors who don't have an appointment.
    """
    logger.info(f"Tool: list_hosts(department={department})")

    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        lookahead = now + timedelta(hours=48)

        if department:
            query = text("""
                SELECT
                    h.id, h.name, h.department,
                    MIN(s.slot_start) AS next_slot
                FROM hosts h
                LEFT JOIN availability_slots s
                    ON s.host_id = h.id
                    AND s.slot_start >= :now
                    AND s.slot_start <= :lookahead
                    AND s.is_booked = false
                WHERE h.is_active = true
                  AND similarity(h.department, :dept) > 0.4
                GROUP BY h.id, h.name, h.department
                ORDER BY h.name
            """)
            result = await session.execute(
                query, {"dept": department, "now": now, "lookahead": lookahead}
            )
        else:
            query = text("""
                SELECT
                    h.id, h.name, h.department,
                    MIN(s.slot_start) AS next_slot
                FROM hosts h
                LEFT JOIN availability_slots s
                    ON s.host_id = h.id
                    AND s.slot_start >= :now
                    AND s.slot_start <= :lookahead
                    AND s.is_booked = false
                WHERE h.is_active = true
                GROUP BY h.id, h.name, h.department
                ORDER BY h.department, h.name
            """)
            result = await session.execute(
                query, {"now": now, "lookahead": lookahead}
            )

        rows = result.fetchall()

        if not rows:
            dept_suffix = f" in {department}" if department else ""
            return HostListResult(
                found=False,
                message=f"No active hosts found{dept_suffix}."
            )

        hosts = [
            HostInfo(
                host_id=str(row.id),
                name=row.name,
                department=row.department,
                next_available_slot=row.next_slot.isoformat() if row.next_slot else None,
            )
            for row in rows
        ]

        logger.info(f"  list_hosts: {len(hosts)} host(s) found" + (f" in '{department}'" if department else ""))
        return HostListResult(found=True, hosts=hosts)
