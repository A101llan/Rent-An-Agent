from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import not_found
from app.models import CustomerProfile
from app.schemas.agents import AgentDetailResponse, PricingPlanResponse, ReviewResponse
from app.services import marketplace as marketplace_service

router = APIRouter(prefix="/agents", tags=["agents"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/{slug}")
async def get_agent(slug: str, db: DbSession):
    data = await marketplace_service.get_agent_by_slug(db, slug)
    if not data:
        raise not_found(message="Agent not found")

    reviews = await marketplace_service.get_agent_reviews(db, data["id"])
    review_responses = []
    for r in reviews:
        cust = await db.execute(select(CustomerProfile).where(CustomerProfile.id == r.customer_id))
        customer = cust.scalar_one_or_none()
        review_responses.append(ReviewResponse(
            id=r.id,
            rating=r.rating,
            title=r.title,
            body=r.body,
            customer_name=customer.display_name if customer else "Anonymous",
            created_at=r.created_at,
        ))

    return {
        "agent": AgentDetailResponse(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            description=data["description"],
            category=data["category"],
            icon_url=data["icon_url"],
            status=data["status"],
            is_featured=data["is_featured"],
            is_verified=data["is_verified"],
            avg_rating=data["avg_rating"],
            review_count=data["review_count"],
            developer_name=data["developer_name"],
            developer_company=data["developer_company"],
            version=data["version"],
            capabilities=data["capabilities"],
            permissions=data["permissions"],
            pricing_plans=[PricingPlanResponse.model_validate(p) for p in data["pricing_plans"] if p.is_active],
            manifest=data["manifest"],
            published_at=data["published_at"],
        ),
        "reviews": review_responses,
    }


from pydantic import BaseModel, Field
from app.core.deps import RequireCustomer

class CreateReviewRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    title: str | None = Field(default=None, max_length=255)
    body: str | None = Field(default=None, max_length=2000)

@router.post("/{agent_id}/reviews", response_model=ReviewResponse, status_code=201)
async def create_review(
    agent_id: UUID,
    body: CreateReviewRequest,
    customer: RequireCustomer,
    db: DbSession,
):
    profile_res = await db.execute(select(CustomerProfile).where(CustomerProfile.user_id == customer.id))
    cust_profile = profile_res.scalar_one_or_none()
    if not cust_profile:
        from app.core.errors import not_found
        raise not_found(message="Customer profile not found")

    review = await marketplace_service.create_agent_review(
        db,
        agent_id=agent_id,
        customer_id=cust_profile.id,
        rating=body.rating,
        title=body.title,
        body=body.body,
    )
    await db.commit()

    return ReviewResponse(
        id=review.id,
        rating=review.rating,
        title=review.title,
        body=review.body,
        customer_name=cust_profile.display_name or "Customer",
        created_at=review.created_at,
    )

