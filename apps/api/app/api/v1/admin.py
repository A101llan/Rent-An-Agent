from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import RequireAdmin, get_db
from app.core.errors import not_found
from app.models import Agent, AgentStatus, VersionStatus
from datetime import UTC, datetime

router = APIRouter(prefix="/admin", tags=["admin"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/agents/pending")
async def pending_agents(user: RequireAdmin, db: DbSession):
    result = await db.execute(
        select(Agent).where(Agent.status == AgentStatus.PENDING_REVIEW)
    )
    agents = result.scalars().all()
    return [{"id": a.id, "slug": a.slug, "name": a.name, "category": a.category} for a in agents]


@router.post("/agents/{agent_id}/approve")
async def approve_agent(agent_id: UUID, user: RequireAdmin, db: DbSession):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise not_found(message="Agent not found")
    agent.status = AgentStatus.PUBLISHED
    agent.is_verified = True
    agent.published_at = datetime.now(UTC)
    return {"status": "approved"}


@router.post("/agents/{agent_id}/reject")
async def reject_agent(agent_id: UUID, user: RequireAdmin, db: DbSession):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise not_found(message="Agent not found")
    agent.status = AgentStatus.DRAFT
    return {"status": "rejected"}


@router.get("/sessions/active")
async def active_sessions(user: RequireAdmin, db: DbSession):
    from app.models import RentalSession, SessionStatus
    result = await db.execute(
        select(RentalSession).where(RentalSession.status == SessionStatus.ACTIVE)
    )
    sessions = result.scalars().all()
    return [{"id": s.id, "rental_id": s.rental_id, "expires_at": s.expires_at.isoformat()} for s in sessions]
