from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_redis
from app.core.session_deps import RequireSession
from app.models import ApprovalScope, CustomerProfile
from app.schemas.approval import ApprovalResponse, ResolveApprovalRequest
from app.services import approval as approval_service

router = APIRouter(prefix="/sessions", tags=["approvals"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/{session_id}/approvals", response_model=list[ApprovalResponse])
async def list_approvals(session: RequireSession, db: DbSession):
    approvals = await approval_service.list_pending_approvals(db, session.id)
    return [ApprovalResponse.model_validate(a) for a in approvals]


@router.post("/{session_id}/approvals/{approval_id}/resolve", response_model=ApprovalResponse)
async def resolve_approval(
    approval_id: UUID,
    body: ResolveApprovalRequest,
    session: RequireSession,
    db: DbSession,
):
    scope = body.scope
    if body.approved and not scope:
        scope = ApprovalScope.ONCE

    cust_result = await db.execute(
        select(CustomerProfile).where(CustomerProfile.id == session.rental.customer_id)
    )
    customer = cust_result.scalar_one()

    approval = await approval_service.resolve_approval(
        db,
        approval_id,
        session.id,
        approved=body.approved,
        scope=scope,
        actor_id=customer.user_id,
    )

    if body.approved and scope and scope == ApprovalScope.SESSION:
        redis = await get_redis()
        await redis.setex(f"approval:session:{session.id}:{approval.action_type}", 86400, "1")

    return ApprovalResponse.model_validate(approval)
