import math
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Agent,
    AgentCapability,
    AgentPermission,
    AgentPricingPlan,
    AgentReview,
    AgentStatus,
    AgentVersion,
    DeveloperProfile,
    VersionStatus,
)


async def list_marketplace_agents(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    category: str | None = None,
    sort: str = "newest",
    featured_only: bool = False,
    verified_only: bool = False,
) -> tuple[list[dict], int]:
    query = (
        select(Agent)
        .join(DeveloperProfile, Agent.developer_id == DeveloperProfile.id)
        .where(Agent.status == AgentStatus.PUBLISHED, Agent.deleted_at.is_(None))
    )

    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(Agent.name.ilike(pattern), Agent.description.ilike(pattern), Agent.category.ilike(pattern))
        )
    if category:
        query = query.where(Agent.category == category)
    if featured_only:
        query = query.where(Agent.is_featured.is_(True))
    if verified_only:
        query = query.where(Agent.is_verified.is_(True))

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    if sort == "rating":
        query = query.order_by(Agent.avg_rating.desc())
    elif sort == "popular":
        query = query.order_by(Agent.review_count.desc())
    elif sort == "name":
        query = query.order_by(Agent.name.asc())
    else:
        query = query.order_by(Agent.published_at.desc().nullslast())

    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.options(selectinload(Agent.developer), selectinload(Agent.versions))

    result = await db.execute(query)
    agents = result.scalars().unique().all()

    items = []
    for agent in agents:
        verified_version = next(
            (v for v in agent.versions if v.status == VersionStatus.VERIFIED),
            agent.versions[0] if agent.versions else None,
        )
        starting_price = None
        pricing_model = None
        capabilities: list[str] = []

        if verified_version:
            caps = await db.execute(
                select(AgentCapability.capability).where(
                    AgentCapability.agent_version_id == verified_version.id
                )
            )
            capabilities = list(caps.scalars().all())
            plan_result = await db.execute(
                select(AgentPricingPlan)
                .where(
                    AgentPricingPlan.agent_version_id == verified_version.id,
                    AgentPricingPlan.is_active.is_(True),
                )
                .order_by(AgentPricingPlan.price_minor.asc())
                .limit(1)
            )
            plan = plan_result.scalar_one_or_none()
            if plan:
                starting_price = plan.price_minor
                pricing_model = plan.pricing_model

        items.append({
            "id": agent.id,
            "slug": agent.slug,
            "name": agent.name,
            "description": agent.description,
            "category": agent.category,
            "icon_url": agent.icon_url,
            "is_featured": agent.is_featured,
            "is_verified": agent.is_verified,
            "avg_rating": float(agent.avg_rating or 0),
            "review_count": agent.review_count,
            "developer_name": agent.developer.display_name if agent.developer else None,
            "starting_price_minor": starting_price,
            "pricing_model": pricing_model,
            "capabilities": capabilities,
        })

    return items, total


async def get_agent_by_slug(db: AsyncSession, slug: str) -> dict | None:
    result = await db.execute(
        select(Agent)
        .options(
            selectinload(Agent.developer),
            selectinload(Agent.versions).selectinload(AgentVersion.pricing_plans),
            selectinload(Agent.versions).selectinload(AgentVersion.capabilities),
            selectinload(Agent.versions).selectinload(AgentVersion.permissions),
        )
        .where(Agent.slug == slug, Agent.deleted_at.is_(None))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return None

    version = next(
        (v for v in agent.versions if v.status == VersionStatus.VERIFIED),
        agent.versions[-1] if agent.versions else None,
    )
    if not version:
        return None

    return {
        "id": agent.id,
        "slug": agent.slug,
        "name": agent.name,
        "description": agent.description,
        "category": agent.category,
        "icon_url": agent.icon_url,
        "status": agent.status,
        "is_featured": agent.is_featured,
        "is_verified": agent.is_verified,
        "avg_rating": float(agent.avg_rating or 0),
        "review_count": agent.review_count,
        "developer_name": agent.developer.display_name if agent.developer else None,
        "developer_company": agent.developer.company_name if agent.developer else None,
        "version": version.version,
        "version_id": version.id,
        "capabilities": [c.capability for c in version.capabilities],
        "permissions": [p.permission for p in version.permissions],
        "pricing_plans": version.pricing_plans,
        "manifest": version.manifest,
        "published_at": agent.published_at,
    }


async def get_agent_reviews(db: AsyncSession, agent_id: UUID, limit: int = 20) -> list[AgentReview]:
    result = await db.execute(
        select(AgentReview)
        .where(AgentReview.agent_id == agent_id)
        .order_by(AgentReview.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def create_agent_review(
    db: AsyncSession,
    *,
    agent_id: UUID,
    customer_id: UUID,
    rating: int,
    title: str | None = None,
    body: str | None = None,
) -> AgentReview:
    review = AgentReview(
        agent_id=agent_id,
        customer_id=customer_id,
        rating=rating,
        title=title,
        body=body,
    )
    db.add(review)
    await db.flush()

    # Recalculate average rating & count
    stats = await db.execute(
        select(
            func.count(AgentReview.id).label("count"),
            func.avg(AgentReview.rating).label("avg"),
        ).where(AgentReview.agent_id == agent_id)
    )
    row = stats.one()
    count = row.count or 0
    avg = float(row.avg or 0)

    agent_res = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = agent_res.scalar_one_or_none()
    if agent:
        agent.review_count = count
        agent.avg_rating = round(avg, 2)
        await db.flush()

    return review


def paginate(total: int, page: int, page_size: int) -> dict:
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)),
    }

