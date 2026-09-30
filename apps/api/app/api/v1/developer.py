from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.deps import RequireDeveloper, get_db
from app.core.errors import bad_request, not_found
from app.models import Agent, AgentStatus, VersionStatus
from app.schemas.agents import (
    CreateAgentRequest,
    CreateVersionRequest,
    DeveloperAgentResponse,
    DeveloperStatsResponse,
)
from app.services import developer as developer_service

router = APIRouter(prefix="/developer", tags=["developer"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/stats", response_model=DeveloperStatsResponse)
async def get_stats(user: RequireDeveloper, db: DbSession):
    profile = await developer_service.get_developer_profile(db, user.id)
    if not profile:
        raise not_found(message="Developer profile not found")
    stats = await developer_service.get_developer_stats(db, profile.id)
    return DeveloperStatsResponse(**stats)


@router.get("/agents", response_model=list[DeveloperAgentResponse])
async def list_agents(user: RequireDeveloper, db: DbSession):
    profile = await developer_service.get_developer_profile(db, user.id)
    if not profile:
        raise not_found(message="Developer profile not found")
    agents = await developer_service.list_developer_agents(db, profile.id)
    return [
        DeveloperAgentResponse(
            id=a.id,
            slug=a.slug,
            name=a.name,
            status=a.status,
            avg_rating=float(a.avg_rating or 0),
            review_count=a.review_count,
            is_verified=a.is_verified,
            created_at=a.created_at,
            latest_version=a.versions[-1].version if a.versions else None,
        )
        for a in agents
    ]


@router.post("/agents", response_model=DeveloperAgentResponse, status_code=201)
async def create_agent(
    body: CreateAgentRequest,
    user: RequireDeveloper,
    db: DbSession,
    request: Request,
):
    profile = await developer_service.get_developer_profile(db, user.id)
    if not profile:
        raise not_found(message="Developer profile not found")

    agent = await developer_service.create_agent(
        db, profile.id,
        name=body.name, slug=body.slug, description=body.description, category=body.category,
    )
    await write_audit_log(
        db, action="AGENT_CREATED", resource_type="agent", resource_id=agent.id,
        actor_id=user.id, request_id=getattr(request.state, "request_id", None),
    )
    return DeveloperAgentResponse(
        id=agent.id, slug=agent.slug, name=agent.name, status=agent.status,
        avg_rating=0, review_count=0, is_verified=False, created_at=agent.created_at,
        latest_version=None,
    )


@router.post("/agents/{agent_id}/versions", status_code=201)
async def create_version(
    agent_id: UUID,
    body: CreateVersionRequest,
    user: RequireDeveloper,
    db: DbSession,
):
    profile = await developer_service.get_developer_profile(db, user.id)
    if not profile:
        raise not_found(message="Developer profile not found")

    from sqlalchemy import select
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.developer_id == profile.id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise not_found(message="Agent not found")

    ver = await developer_service.create_agent_version(
        db, agent,
        version=body.version, manifest=body.manifest.model_dump(exclude_unset=True),
        image_registry=body.image_registry, image_name=body.image_name,
        image_digest=body.image_digest, capabilities=body.capabilities,
        permissions=body.permissions, pricing_model=body.pricing_model,
        price_minor=body.price_minor, duration_minutes=body.duration_minutes,
    )
    return {"version_id": ver.id, "version": ver.version, "status": ver.status.value}


@router.post("/agents/{agent_id}/publish")
async def publish_agent(agent_id: UUID, user: RequireDeveloper, db: DbSession, request: Request):
    profile = await developer_service.get_developer_profile(db, user.id)
    if not profile:
        raise not_found(message="Developer profile not found")

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models import AgentVersion

    result = await db.execute(
        select(Agent)
        .options(selectinload(Agent.versions))
        .where(Agent.id == agent_id, Agent.developer_id == profile.id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise not_found(message="Agent not found")

    verified = any(v.status == VersionStatus.VERIFIED for v in agent.versions)
    if not verified:
        for v in agent.versions:
            v.status = VersionStatus.VERIFIED
        agent.status = AgentStatus.PUBLISHED
        from datetime import UTC, datetime
        agent.published_at = datetime.now(UTC)
    else:
        agent.status = AgentStatus.PENDING_REVIEW

    await write_audit_log(
        db, action="AGENT_PUBLISHED", resource_type="agent", resource_id=agent.id,
        actor_id=user.id, request_id=getattr(request.state, "request_id", None),
    )
    return {"status": agent.status.value}
