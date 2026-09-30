from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import (
    Agent,
    AgentArtifact,
    AgentCapability,
    AgentExecution,
    AgentPermission,
    AgentPricingPlan,
    AgentStatus,
    AgentVersion,
    DeveloperProfile,
    Rental,
    RentalStatus,
    Transaction,
    TransactionStatus,
    VersionStatus,
)


async def get_developer_profile(db: AsyncSession, user_id: UUID) -> DeveloperProfile | None:
    result = await db.execute(
        select(DeveloperProfile).where(DeveloperProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_developer_agents(db: AsyncSession, developer_id: UUID) -> list[Agent]:
    result = await db.execute(
        select(Agent)
        .options(selectinload(Agent.versions))
        .where(Agent.developer_id == developer_id, Agent.deleted_at.is_(None))
        .order_by(Agent.created_at.desc())
    )
    return list(result.scalars().unique().all())


async def get_developer_stats(db: AsyncSession, developer_id: UUID) -> dict:
    agents_result = await db.execute(
        select(func.count()).select_from(Agent).where(
            Agent.developer_id == developer_id,
            Agent.status == AgentStatus.PUBLISHED,
        )
    )
    published = agents_result.scalar() or 0

    agent_ids_q = select(Agent.id).where(Agent.developer_id == developer_id)
    rentals_result = await db.execute(
        select(func.count()).select_from(Rental).where(
            Rental.agent_id.in_(agent_ids_q),
            Rental.status == RentalStatus.ACTIVE,
        )
    )
    active_rentals = rentals_result.scalar() or 0

    exec_result = await db.execute(
        select(func.count()).select_from(AgentExecution).where(
            AgentExecution.agent_version_id.in_(
                select(AgentVersion.id).where(
                    AgentVersion.agent_id.in_(agent_ids_q)
                )
            )
        )
    )
    total_executions = exec_result.scalar() or 0

    revenue_result = await db.execute(
        select(func.coalesce(func.sum(Transaction.developer_amount_minor), 0)).where(
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.rental_id.in_(
                select(Rental.id).where(Rental.agent_id.in_(agent_ids_q))
            ),
        )
    )
    revenue = revenue_result.scalar() or 0

    rating_result = await db.execute(
        select(func.coalesce(func.avg(Agent.avg_rating), 0)).where(
            Agent.developer_id == developer_id,
            Agent.status == AgentStatus.PUBLISHED,
        )
    )
    avg_rating = float(rating_result.scalar() or 0)

    return {
        "published_agents": published,
        "active_rentals": active_rentals,
        "total_executions": total_executions,
        "total_revenue_minor": int(revenue),
        "avg_rating": round(avg_rating, 2),
    }


async def create_agent(
    db: AsyncSession,
    developer_id: UUID,
    *,
    name: str,
    slug: str,
    description: str,
    category: str,
) -> Agent:
    agent = Agent(
        developer_id=developer_id,
        name=name,
        slug=slug,
        description=description,
        category=category,
        status=AgentStatus.DRAFT,
    )
    db.add(agent)
    await db.flush()
    return agent


async def create_agent_version(
    db: AsyncSession,
    agent: Agent,
    *,
    version: str,
    manifest: dict,
    image_registry: str,
    image_name: str | None,
    image_digest: str | None,
    capabilities: list[str],
    permissions: list[str],
    pricing_model,
    price_minor: int,
    duration_minutes: int | None,
) -> AgentVersion:
    ver = AgentVersion(
        agent_id=agent.id,
        version=version,
        manifest=manifest,
        runtime_requirements=manifest.get("resources", {}),
        status=VersionStatus.PENDING_VERIFICATION,
    )
    db.add(ver)
    await db.flush()

    # Local-runtime versions (manifest.runtime.type == "local") ship no container image.
    if image_name is not None and image_digest is not None:
        db.add(AgentArtifact(
            agent_version_id=ver.id,
            image_registry=image_registry,
            image_name=image_name,
            image_digest=image_digest,
        ))

    for cap in capabilities:
        db.add(AgentCapability(agent_version_id=ver.id, capability=cap))
    for perm in permissions:
        db.add(AgentPermission(agent_version_id=ver.id, permission=perm))

    db.add(AgentPricingPlan(
        agent_version_id=ver.id,
        name="Standard",
        pricing_model=pricing_model,
        price_minor=price_minor,
        currency=settings.default_currency,
        duration_minutes=duration_minutes,
    ))

    await db.flush()
    return ver
