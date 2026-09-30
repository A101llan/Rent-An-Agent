from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.errors import bad_request, not_found
from app.models import (
    ApprovalRequest,
    ApprovalScope,
    ApprovalStatus,
    AgentExecution,
    ExecutionStatus,
    RentalSession,
)


async def create_approval_request(
    db: AsyncSession,
    *,
    session: RentalSession,
    execution: AgentExecution,
    action_type: str,
    title: str,
    description: str,
    details: dict | None,
) -> ApprovalRequest:
    execution.status = ExecutionStatus.WAITING_FOR_APPROVAL
    approval = ApprovalRequest(
        session_id=session.id,
        execution_id=execution.id,
        action_type=action_type,
        title=title,
        description=description,
        details=details,
        status=ApprovalStatus.PENDING,
    )
    db.add(approval)
    await db.flush()
    return approval


async def list_pending_approvals(db: AsyncSession, session_id: UUID) -> list[ApprovalRequest]:
    result = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.session_id == session_id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
        ).order_by(ApprovalRequest.created_at.desc())
    )
    return list(result.scalars().all())


async def resolve_approval(
    db: AsyncSession,
    approval_id: UUID,
    session_id: UUID,
    *,
    approved: bool,
    scope: ApprovalScope | None = None,
    actor_id: UUID | None = None,
) -> ApprovalRequest:
    result = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.session_id == session_id,
        )
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise not_found(message="Approval request not found")
    if approval.status != ApprovalStatus.PENDING:
        raise bad_request(code="APPROVAL_ALREADY_RESOLVED", message="Approval already resolved")

    approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
    approval.scope = scope if approved else None
    approval.resolved_at = datetime.now(UTC)

    exec_result = await db.execute(
        select(AgentExecution).where(AgentExecution.id == approval.execution_id)
    )
    execution = exec_result.scalar_one()

    if approved:
        execution.status = ExecutionStatus.COMPLETED
        execution.output_metadata = {
            "status": "completed",
            "output": f"Action {approval.action_type} approved and executed.",
            "approved": True,
            "scope": scope.value if scope else "once",
        }
        execution.completed_at = datetime.now(UTC)
    else:
        execution.status = ExecutionStatus.CANCELLED
        execution.output_metadata = {"status": "cancelled", "output": "Action denied by user."}
        execution.completed_at = datetime.now(UTC)

    await write_audit_log(
        db,
        action="PERMISSION_GRANTED" if approved else "PERMISSION_REVOKED",
        resource_type="approval",
        resource_id=approval.id,
        actor_id=actor_id,
        metadata={"action_type": approval.action_type, "scope": scope.value if scope else None},
    )

    return approval


def session_has_approval_for_action(session_id: UUID, action_type: str, cache: dict) -> bool:
    """In-memory session-scoped approval cache (populated on SESSION scope approve)."""
    key = f"{session_id}:{action_type}"
    return cache.get(key, False)
