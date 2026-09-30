from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import RequireCustomer, get_db
from app.core.errors import AppError
from app.core.session_deps import RequireSession, RequireSessionStrict
from app.models import Agent, CustomerProfile, Rental, RentalSession
from app.schemas.embed import EmbedSnippetResponse
from app.schemas.rentals import (
    CreateRentalRequest,
    CreateSessionRequest,
    ExecuteRequest,
    ExecuteResponse,
    ExecutionHistoryItem,
    ExtendSessionRequest,
    HireAgentRequest,
    HireAgentResponse,
    LocalClaimResponse,
    LocalRuntimeInfo,
    LocalUsageRequest,
    RentalResponse,
    SessionIntegrationInfo,
    SessionResponse,
    UsageRecordResponse,
)
from app.services import rental as rental_service
from app.services.integration import build_session_integration
from app.services.embed import build_embed_snippet

router = APIRouter(tags=["rentals"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _api_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _web_base_url(request: Request) -> str:
    from app.config import settings

    if settings.cors_origin_list:
        return settings.cors_origin_list[0].rstrip("/")
    return str(request.base_url).replace(":8000", ":3000").rstrip("/")


def _session_response(
    session: RentalSession,
    *,
    token: str | None = None,
    embed_key: str | None = None,
    request: Request | None = None,
) -> SessionResponse:
    agent = session.rental.agent
    runtime_status = session.runtime_instance.status.value if session.runtime_instance else None
    integration = None
    embed = None
    if request and token:
        integration = SessionIntegrationInfo.model_validate(
            build_session_integration(
                api_base_url=_api_base_url(request),
                session_id=session.id,
                session_token=token,
            )
        )
    if request and embed_key:
        embed = EmbedSnippetResponse.model_validate(
            build_embed_snippet(embed_key, _web_base_url(request))
        )
    return SessionResponse(
        id=session.id,
        rental_id=session.rental_id,
        status=session.status,
        started_at=session.started_at,
        expires_at=session.expires_at,
        last_activity_at=session.last_activity_at,
        agent_name=agent.name,
        agent_slug=agent.slug,
        runtime_status=runtime_status,
        runtime_provider=session.runtime_instance.runtime_provider if session.runtime_instance else None,
        session_token=token,
        integration=integration,
        embed=embed,
    )


async def _load_session(db: AsyncSession, session_id) -> RentalSession:
    result = await db.execute(
        select(RentalSession)
        .options(
            selectinload(RentalSession.rental).selectinload(Rental.agent),
            selectinload(RentalSession.rental).selectinload(Rental.agent_version),
            selectinload(RentalSession.rental).selectinload(Rental.customer),
            selectinload(RentalSession.runtime_instance),
        )
        .where(RentalSession.id == session_id)
    )
    return result.scalar_one()


@router.post("/rentals/hire", response_model=HireAgentResponse, status_code=201)
async def hire_agent(
    body: HireAgentRequest,
    user: RequireCustomer,
    db: DbSession,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """One-call hire: create rental, start session, return session token for API integration."""
    customer = await rental_service.get_customer_for_user(db, user.id)
    key = idempotency_key or body.idempotency_key

    rental = await rental_service.create_rental(
        db,
        customer,
        agent_slug=body.agent_slug,
        pricing_plan_id=body.pricing_plan_id,
        duration_minutes=body.duration_minutes,
        idempotency_key=key and f"hire_{key}",
        request_id=getattr(request.state, "request_id", None),
    )
    session, token, embed_key = await rental_service.create_session(
        db,
        customer,
        rental_id=rental.id,
        idempotency_key=key and f"hire_session_{key}",
        request_id=getattr(request.state, "request_id", None),
    )
    session = await _load_session(db, session.id)
    agent = session.rental.agent

    rental_resp = RentalResponse(
        id=rental.id,
        agent_id=rental.agent_id,
        agent_name=agent.name,
        agent_slug=agent.slug,
        status=rental.status,
        started_at=rental.started_at,
        expires_at=rental.expires_at,
        total_cost_minor=rental.total_cost_minor,
        currency=rental.currency,
        created_at=rental.created_at,
    )
    integration = SessionIntegrationInfo.model_validate(
        build_session_integration(
            api_base_url=_api_base_url(request),
            session_id=session.id,
            session_token=token,
        )
    )
    embed = EmbedSnippetResponse.model_validate(
        build_embed_snippet(embed_key, _web_base_url(request))
    )
    runtime_provider = session.runtime_instance.runtime_provider if session.runtime_instance else None
    local_info = None
    if runtime_provider == rental_service.LOCAL_RUNTIME_PROVIDER:
        sessions_url = f"{_api_base_url(request)}/api/v1/sessions/{session.id}"
        local_info = LocalRuntimeInfo(
            session_id=session.id,
            claim_endpoint=f"{sessions_url}/local/claim",
            usage_endpoint=f"{sessions_url}/usage",
        )
    return HireAgentResponse(
        rental=rental_resp,
        session=_session_response(session, token=token, embed_key=embed_key, request=request),
        session_token=token,
        integration=integration,
        embed=embed,
        runtime_provider=runtime_provider,
        local=local_info,
    )


@router.post("/rentals", response_model=RentalResponse, status_code=201)
async def create_rental(
    body: CreateRentalRequest,
    user: RequireCustomer,
    db: DbSession,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    customer = await rental_service.get_customer_for_user(db, user.id)
    rental = await rental_service.create_rental(
        db,
        customer,
        agent_slug=body.agent_slug,
        pricing_plan_id=body.pricing_plan_id,
        duration_minutes=body.duration_minutes,
        idempotency_key=idempotency_key or body.idempotency_key,
        request_id=getattr(request.state, "request_id", None),
    )
    agent_result = await db.execute(select(Agent).where(Agent.id == rental.agent_id))
    agent = agent_result.scalar_one()
    return RentalResponse(
        id=rental.id,
        agent_id=rental.agent_id,
        agent_name=agent.name,
        agent_slug=agent.slug,
        status=rental.status,
        started_at=rental.started_at,
        expires_at=rental.expires_at,
        total_cost_minor=rental.total_cost_minor,
        currency=rental.currency,
        created_at=rental.created_at,
    )


@router.get("/rentals", response_model=list[RentalResponse])
async def list_rentals(user: RequireCustomer, db: DbSession):
    customer = await rental_service.get_customer_for_user(db, user.id)
    result = await db.execute(
        select(Rental, Agent)
        .join(Agent, Rental.agent_id == Agent.id)
        .where(Rental.customer_id == customer.id)
        .order_by(Rental.created_at.desc())
    )
    return [
        RentalResponse(
            id=r.id,
            agent_id=r.agent_id,
            agent_name=a.name,
            agent_slug=a.slug,
            status=r.status,
            started_at=r.started_at,
            expires_at=r.expires_at,
            total_cost_minor=r.total_cost_minor,
            currency=r.currency,
            created_at=r.created_at,
        )
        for r, a in result.all()
    ]


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    user: RequireCustomer,
    db: DbSession,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    customer = await rental_service.get_customer_for_user(db, user.id)
    session, token, embed_key = await rental_service.create_session(
        db,
        customer,
        rental_id=body.rental_id,
        idempotency_key=idempotency_key or body.idempotency_key,
        request_id=getattr(request.state, "request_id", None),
    )
    session = await _load_session(db, session.id)
    return _session_response(session, token=token, embed_key=embed_key, request=request)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session: RequireSession):
    await rental_service.validate_session_active(session)
    return _session_response(session)


@router.get("/sessions/{session_id}/integration", response_model=SessionIntegrationInfo)
async def get_session_integration(session: RequireSession, request: Request):
    await rental_service.validate_session_active(session)
    return SessionIntegrationInfo.model_validate(
        build_session_integration(
            api_base_url=_api_base_url(request),
            session_id=session.id,
            session_token=None,
        )
    )


@router.post("/sessions/{session_id}/extend", response_model=SessionResponse)
async def extend_session(
    body: ExtendSessionRequest,
    session: RequireSession,
    db: DbSession,
):
    cust_result = await db.execute(
        select(CustomerProfile).where(CustomerProfile.id == session.rental.customer_id)
    )
    customer = cust_result.scalar_one()
    session = await rental_service.extend_session(db, session, customer, body.duration_minutes)
    session = await _load_session(db, session.id)
    return _session_response(session)


@router.post("/sessions/{session_id}/execute", response_model=ExecuteResponse)
async def execute(
    session: RequireSession,
    body: ExecuteRequest,
    db: DbSession,
    request: Request,
):
    execution = await rental_service.execute_agent(
        db,
        session,
        input_data=body.input,
        context=body.context,
        request_id=getattr(request.state, "request_id", None),
    )
    output = execution.output_metadata
    approval_id = None
    if execution.status.value == "waiting_for_approval":
        from app.models import ApprovalRequest, ApprovalStatus

        result = await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.execution_id == execution.id,
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
        )
        approval = result.scalar_one_or_none()
        if approval:
            approval_id = approval.id

    return ExecuteResponse(
        execution_id=execution.id,
        status=execution.status.value,
        output=output.get("output") if output and output.get("status") == "completed" else None,
        usage=output.get("usage") if output else None,
        approval_id=approval_id,
        approval=output.get("approval") if output and output.get("status") == "waiting_for_approval" else None,
    )


@router.post("/sessions/{session_id}/local/claim", response_model=LocalClaimResponse)
async def claim_local_session(session: RequireSessionStrict, db: DbSession, request: Request):
    """Device sidecar claims a local session. Auth: X-Session-Token or owner JWT. No expiry extension."""
    session, version = await rental_service.claim_local_session(
        db, session, request_id=getattr(request.state, "request_id", None)
    )
    return LocalClaimResponse(
        session_id=session.id,
        expires_at=session.expires_at,
        manifest=rental_service.manifest_to_dict(version.manifest),
        agent_slug=session.rental.agent.slug,
        agent_version=version.version,
        runtime_provider=rental_service.LOCAL_RUNTIME_PROVIDER,
    )


@router.post("/sessions/{session_id}/usage", response_model=UsageRecordResponse, status_code=201)
async def report_session_usage(request: Request, session: RequireSessionStrict, db: DbSession):
    """Device sidecar reports metering for a local session. Writes a UsageRecord only."""
    try:
        body = LocalUsageRequest.model_validate(await request.json())
    except (ValidationError, TypeError, ValueError) as exc:
        raise AppError(422, "VALIDATION_ERROR", "Request validation failed") from exc
    record = await rental_service.record_local_usage(
        db,
        session,
        metric_type=body.metric_type,
        quantity=body.quantity,
        unit=body.unit,
        execution_id=body.execution_id,
    )
    return UsageRecordResponse(
        id=record.id,
        session_id=record.session_id,
        execution_id=record.execution_id,
        metric_type=record.metric_type,
        quantity=float(record.quantity),
        unit=record.unit,
        recorded_at=record.recorded_at,
    )


@router.get("/sessions/{session_id}/executions", response_model=list[ExecutionHistoryItem])
async def execution_history(session: RequireSession, db: DbSession):
    from app.models import AgentExecution

    result = await db.execute(
        select(AgentExecution)
        .where(AgentExecution.session_id == session.id)
        .order_by(AgentExecution.created_at.desc())
        .limit(50)
    )
    items = []
    for ex in result.scalars():
        inp = ex.input_metadata or {}
        out = ex.output_metadata or {}
        items.append(
            ExecutionHistoryItem(
                id=ex.id,
                status=ex.status.value,
                input_preview=str(inp.get("input", ""))[:100] or None,
                output_preview=str(out.get("output", ""))[:100] or None,
                duration_ms=ex.duration_ms,
                created_at=ex.created_at,
                completed_at=ex.completed_at,
            )
        )
    return items
