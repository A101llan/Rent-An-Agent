from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models import ApprovalScope, ApprovalStatus


class ApprovalResponse(BaseModel):
    id: UUID
    session_id: UUID
    execution_id: UUID
    action_type: str
    title: str
    description: str
    details: dict | None
    status: ApprovalStatus
    scope: ApprovalScope | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ResolveApprovalRequest(BaseModel):
    approved: bool
    scope: ApprovalScope | None = None  # once | session — required when approved
