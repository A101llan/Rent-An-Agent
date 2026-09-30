from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import RentalStatus, SessionStatus
from app.schemas.embed import EmbedSnippetResponse


class SessionIntegrationInfo(BaseModel):
    api_base_url: str
    session_id: UUID
    auth: dict
    endpoints: dict
    examples: dict


class CreateRentalRequest(BaseModel):
    agent_slug: str
    pricing_plan_id: UUID
    duration_minutes: int = Field(default=30, ge=5, le=480)
    idempotency_key: str | None = None


class RentalResponse(BaseModel):
    id: UUID
    agent_id: UUID
    agent_name: str
    agent_slug: str
    status: RentalStatus
    started_at: datetime | None
    expires_at: datetime | None
    total_cost_minor: int
    currency: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateSessionRequest(BaseModel):
    rental_id: UUID
    idempotency_key: str | None = None


class SessionResponse(BaseModel):
    id: UUID
    rental_id: UUID
    status: SessionStatus
    started_at: datetime | None
    expires_at: datetime
    last_activity_at: datetime | None
    agent_name: str
    agent_slug: str
    runtime_status: str | None = None
    runtime_provider: str | None = Field(
        default=None,
        description='"local" = runs on the renter\'s device via the local sidecar (claim it with '
        'POST /sessions/{id}/local/claim); any other value = server runtime.',
    )
    session_token: str | None = Field(
        default=None,
        description="Shown once at session creation. Use as X-Session-Token for API integration.",
    )
    integration: SessionIntegrationInfo | None = None
    embed: EmbedSnippetResponse | None = Field(
        default=None,
        description="Embed widget snippet and API key (shown once at session creation).",
    )

    model_config = {"from_attributes": True}


class HireAgentRequest(BaseModel):
    agent_slug: str
    pricing_plan_id: UUID
    duration_minutes: int = Field(default=30, ge=5, le=480)
    idempotency_key: str | None = None


class LocalRuntimeInfo(BaseModel):
    """What the device sidecar needs to claim a local session (auth = session_token)."""

    session_id: UUID
    claim_endpoint: str
    usage_endpoint: str
    auth_header: str = "X-Session-Token"


class HireAgentResponse(BaseModel):
    rental: RentalResponse
    session: SessionResponse
    session_token: str = Field(description="Session-scoped API token. Store securely; not retrievable later.")
    integration: SessionIntegrationInfo
    embed: EmbedSnippetResponse = Field(description="Copy-paste widget for your own system.")
    runtime_provider: str | None = Field(
        default=None, description='Same as session.runtime_provider ("local" for device-side agents).'
    )
    local: LocalRuntimeInfo | None = Field(
        default=None, description="Present only for local sessions: sidecar claim details."
    )


class LocalClaimResponse(BaseModel):
    session_id: UUID
    expires_at: datetime
    manifest: dict
    agent_slug: str
    agent_version: str
    runtime_provider: str = "local"


class LocalUsageRequest(BaseModel):
    """Metering only. Unknown fields are rejected so no document content can be uploaded."""

    metric_type: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_.:-]+$")
    quantity: float = Field(gt=0, le=1_000_000_000_000, allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_./-]+$")
    execution_id: UUID | None = None

    model_config = {"extra": "forbid"}


class UsageRecordResponse(BaseModel):
    id: UUID
    session_id: UUID
    execution_id: UUID | None
    metric_type: str
    quantity: float
    unit: str
    recorded_at: datetime | None


class ExtendSessionRequest(BaseModel):
    duration_minutes: int = Field(default=30, ge=5, le=480)


class ExecuteRequest(BaseModel):
    input: str | dict
    context: dict = {}


class ExecuteResponse(BaseModel):
    execution_id: UUID
    status: str
    output: dict | str | None
    usage: dict | None = None
    approval_id: UUID | None = None
    approval: dict | None = None


class ExecutionHistoryItem(BaseModel):
    id: UUID
    status: str
    input_preview: str | None
    output_preview: str | None
    duration_ms: int | None
    created_at: datetime
    completed_at: datetime | None
