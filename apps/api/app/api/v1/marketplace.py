from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.schemas.agents import AgentDetailResponse, AgentListItem, PricingPlanResponse, ReviewResponse
from app.services import marketplace as marketplace_service

router = APIRouter(prefix="/marketplace", tags=["marketplace"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/agents")
async def list_agents(
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    category: str | None = None,
    sort: str = Query("newest", pattern="^(newest|rating|popular|name)$"),
    featured: bool = False,
    verified: bool = False,
):
    items, total = await marketplace_service.list_marketplace_agents(
        db,
        page=page,
        page_size=page_size,
        search=search,
        category=category,
        sort=sort,
        featured_only=featured,
        verified_only=verified,
    )
    meta = marketplace_service.paginate(total, page, page_size)
    return {
        "items": [AgentListItem(**item) for item in items],
        **meta,
    }


@router.get("/featured")
async def featured_agents(db: DbSession):
    items, _ = await marketplace_service.list_marketplace_agents(
        db, page=1, page_size=6, featured_only=True, sort="rating"
    )
    return [AgentListItem(**item) for item in items]


@router.get("/categories")
async def categories(db: DbSession):
    from sqlalchemy import func
    from app.models import Agent, AgentStatus

    result = await db.execute(
        select(Agent.category, func.count())
        .where(Agent.status == AgentStatus.PUBLISHED, Agent.deleted_at.is_(None))
        .group_by(Agent.category)
        .order_by(func.count().desc())
    )
    return [{"category": row[0], "count": row[1]} for row in result.all()]
