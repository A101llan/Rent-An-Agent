import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.audit import write_audit_log
from app.core.errors import bad_request, conflict, forbidden, not_found, session_expired, unauthorized
from app.core.security import hash_token
from app.models import (
    AgentCredential,
    AgentExecution,
    AgentPricingPlan,
    AgentVersion,
    CustomerProfile,
    ExecutionStatus,
    PricingModel,
    Rental,
    RentalSession,
    RentalStatus,
    RuntimeInstance,
    RuntimeStatus,
    SessionStatus,
    TransactionType,
    UsageRecord,
)
from app.services.billing import billing_provider
from app.services.marketplace import get_agent_by_slug

_SESSION_LOAD_OPTIONS = (
    selectinload(RentalSession.rental).selectinload(Rental.agent),
    selectinload(RentalSession.rental).selectinload(Rental.agent_version),
    selectinload(RentalSession.rental).selectinload(Rental.customer),
    selectinload(RentalSession.runtime_instance),
)


def _calculate_cost(price_minor: int, pricing_model: PricingModel, duration_minutes: int) -> int:
    if pricing_model == PricingModel.PER_HOUR:
        return (price_minor * duration_minutes) // 60
    if pricing_model == PricingModel.PER_MINUTE:
        return price_minor * duration_minutes
    return price_minor



# --- Local (device sidecar) runtime support -------------------------------------------
# Agents whose manifest declares runtime.type == "local" run on the renter's device via the
# local sidecar. The cloud only records the rental/session entitlement and usage; it never
# calls runtime-manager for these sessions.
LOCAL_RUNTIME_PROVIDER = "local"


def _manifest_get(obj, key: str):
    """Read a key from a manifest fragment that may be a dict or a (pydantic) model."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def get_manifest_runtime_type(manifest) -> str | None:
    runtime = _manifest_get(manifest, "runtime")
    runtime_type = _manifest_get(runtime, "type")
    if isinstance(runtime_type, str) and runtime_type.strip():
        return runtime_type.strip().lower()
    return None


def is_local_manifest(manifest) -> bool:
    """True only when manifest.runtime.type == "local"; missing runtime => server path."""
    return get_manifest_runtime_type(manifest) == LOCAL_RUNTIME_PROVIDER


def manifest_to_dict(manifest) -> dict:
    if manifest is None:
        return {}
    if isinstance(manifest, dict):
        return dict(manifest)
    if hasattr(manifest, "model_dump"):
        return manifest.model_dump(mode="json")
    return {}


def is_local_session(session: RentalSession) -> bool:
    runtime = session.runtime_instance
    return bool(runtime and runtime.runtime_provider == LOCAL_RUNTIME_PROVIDER)


def _int_or(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def create_rental(
    db: AsyncSession,
    customer: CustomerProfile,
    *,
    agent_slug: str,
    pricing_plan_id: UUID,
    duration_minutes: int,
    idempotency_key: str | None,
    request_id: str | None = None,
) -> Rental:
    if idempotency_key:
        existing = await db.execute(
            select(Rental).where(Rental.idempotency_key == idempotency_key)
        )
        rental = existing.scalar_one_or_none()
        if rental:
            return rental

    agent_data = await get_agent_by_slug(db, agent_slug)
    if not agent_data or agent_data["status"].value != "published":
        raise not_found(code="AGENT_NOT_FOUND", message="Agent not found or not published")

    plan_result = await db.execute(
        select(AgentPricingPlan).where(
            AgentPricingPlan.id == pricing_plan_id,
            AgentPricingPlan.is_active.is_(True),
        )
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise bad_request(code="INVALID_PRICING_PLAN", message="Pricing plan not found")

    version_id = agent_data["version_id"]
    total_cost = _calculate_cost(plan.price_minor, plan.pricing_model, duration_minutes)
    now = datetime.now(UTC)

    charge = await billing_provider.charge(
        db,
        customer_id=customer.id,
        gross_amount_minor=total_cost,
        currency=plan.currency,
        idempotency_key=idempotency_key and f"charge_{idempotency_key}",
    )
    if not charge.success:
        raise bad_request(code="PAYMENT_FAILED", message="Payment could not be processed")

    rental = Rental(
        customer_id=customer.id,
        agent_id=agent_data["id"],
        agent_version_id=version_id,
        pricing_plan_id=plan.id,
        status=RentalStatus.ACTIVE,
        started_at=now,
        expires_at=now + timedelta(minutes=duration_minutes),
        total_cost_minor=total_cost,
        currency=plan.currency,
        idempotency_key=idempotency_key,
    )
    db.add(rental)
    await db.flush()

    charge.transaction.rental_id = rental.id

    await write_audit_log(
        db,
        action="RENTAL_CREATED",
        resource_type="rental",
        resource_id=rental.id,
        actor_id=customer.user_id,
        metadata={"agent_slug": agent_slug, "cost_minor": total_cost},
        request_id=request_id,
    )

    return rental


async def create_session(
    db: AsyncSession,
    customer: CustomerProfile,
    *,
    rental_id: UUID,
    idempotency_key: str | None,
    request_id: str | None = None,
) -> tuple[RentalSession, str, str]:
    result = await db.execute(
        select(Rental)
        .options(selectinload(Rental.agent))
        .where(Rental.id == rental_id, Rental.customer_id == customer.id)
    )
    rental = result.scalar_one_or_none()
    if not rental:
        raise forbidden(message="Rental not found")
    if rental.status != RentalStatus.ACTIVE:
        raise bad_request(code="RENTAL_INACTIVE", message="Rental is not active")
    if rental.expires_at and rental.expires_at < datetime.now(UTC):
        rental.status = RentalStatus.EXPIRED
        raise bad_request(code="RENTAL_EXPIRED", message="Rental has expired")

    now = datetime.now(UTC)
    expires = rental.expires_at or (now + timedelta(minutes=30))
    raw_token = secrets.token_urlsafe(32)

    session = RentalSession(
        rental_id=rental.id,
        token_hash=hash_token(raw_token),
        status=SessionStatus.PENDING,
        expires_at=expires,
    )
    db.add(session)
    await db.flush()

    version_result = await db.execute(
        select(AgentVersion).where(AgentVersion.id == rental.agent_version_id)
    )
    version = version_result.scalar_one_or_none()
    if version is not None and is_local_manifest(version.manifest):
        runtime = await _create_local_runtime(db, session, version, request_id)
    else:
        runtime = await _provision_runtime(db, session, rental.agent_version_id, request_id)
    session.runtime_instance_id = runtime.id
    session.status = SessionStatus.ACTIVE
    session.started_at = now
    session.last_activity_at = now

    await write_audit_log(
        db,
        action="SESSION_STARTED",
        resource_type="session",
        resource_id=session.id,
        actor_id=customer.user_id,
        request_id=request_id,
    )

    from app.services.embed_key import create_embed_key

    _, embed_raw = await create_embed_key(db, session.id)

    return session, raw_token, embed_raw


async def _provision_runtime(
    db: AsyncSession,
    session: RentalSession,
    agent_version_id: UUID,
    request_id: str | None,
) -> RuntimeInstance:
    version_result = await db.execute(
        select(AgentVersion).where(AgentVersion.id == agent_version_id)
    )
    version = version_result.scalar_one()

    runtime = RuntimeInstance(
        session_id=session.id,
        agent_version_id=agent_version_id,
        runtime_provider="mock",
        status=RuntimeStatus.PROVISIONING,
        cpu_limit=version.manifest.get("resources", {}).get("cpu", 1),
        memory_limit_mb=version.manifest.get("resources", {}).get("memory_mb", 1024),
    )
    db.add(runtime)
    await db.flush()

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.runtime_manager_url}/runtimes",
                json={
                    "runtime_id": str(runtime.id),
                    "session_id": str(session.id),
                    "manifest": version.manifest,
                },
                headers={"X-Request-ID": request_id or ""},
            )
            if resp.status_code == 200:
                data = resp.json()
                runtime.runtime_identifier = data.get("identifier")
                runtime.status = RuntimeStatus.RUNNING
                runtime.started_at = datetime.now(UTC)
            else:
                runtime.status = RuntimeStatus.FAILED
    except Exception:
        runtime.status = RuntimeStatus.RUNNING
        runtime.runtime_identifier = f"mock-{runtime.id}"
        runtime.started_at = datetime.now(UTC)

    await write_audit_log(
        db,
        action="RUNTIME_CREATED",
        resource_type="runtime",
        resource_id=runtime.id,
        metadata={"provider": runtime.runtime_provider},
        request_id=request_id,
    )

    return runtime



async def _create_local_runtime(
    db: AsyncSession,
    session: RentalSession,
    version: AgentVersion,
    request_id: str | None,
) -> RuntimeInstance:
    """Record a device-side runtime. No runtime-manager call; the sidecar claims it later."""
    resources = _manifest_get(version.manifest, "resources") or {}
    runtime = RuntimeInstance(
        session_id=session.id,
        agent_version_id=version.id,
        runtime_provider=LOCAL_RUNTIME_PROVIDER,
        status=RuntimeStatus.PROVISIONING,
        cpu_limit=_int_or(_manifest_get(resources, "cpu"), 1),
        memory_limit_mb=_int_or(_manifest_get(resources, "memory_mb"), 1024),
    )
    db.add(runtime)
    await db.flush()

    await write_audit_log(
        db,
        action="RUNTIME_CREATED",
        resource_type="runtime",
        resource_id=runtime.id,
        metadata={"provider": runtime.runtime_provider},
        request_id=request_id,
    )
    return runtime


async def get_customer_for_user(db: AsyncSession, user_id: UUID) -> CustomerProfile:
    result = await db.execute(select(CustomerProfile).where(CustomerProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise forbidden(message="Customer profile required")
    return profile


async def get_session_by_token(
    db: AsyncSession,
    session_id: UUID,
    raw_token: str,
) -> RentalSession:
    token_hash = hash_token(raw_token)
    result = await db.execute(
        select(RentalSession)
        .options(*_SESSION_LOAD_OPTIONS)
        .where(RentalSession.id == session_id, RentalSession.token_hash == token_hash)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise unauthorized(code="INVALID_SESSION_TOKEN", message="Invalid session token")
    return session


async def get_session_for_user(
    db: AsyncSession,
    session_id: UUID,
    customer: CustomerProfile,
) -> RentalSession:
    result = await db.execute(
        select(RentalSession)
        .join(Rental, RentalSession.rental_id == Rental.id)
        .options(*_SESSION_LOAD_OPTIONS)
        .where(RentalSession.id == session_id, Rental.customer_id == customer.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise forbidden(message="Session not found")
    return session


async def validate_session_active(session: RentalSession) -> None:
    if session.status == SessionStatus.EXPIRED:
        raise session_expired()
    if session.status == SessionStatus.TERMINATED:
        raise session_expired(message="This session has been terminated.")
    if session.expires_at < datetime.now(UTC):
        session.status = SessionStatus.EXPIRED
        raise session_expired()



async def get_session_by_id(db: AsyncSession, session_id: UUID) -> RentalSession | None:
    result = await db.execute(
        select(RentalSession)
        .options(*_SESSION_LOAD_OPTIONS)
        .where(RentalSession.id == session_id)
    )
    return result.scalar_one_or_none()


def ensure_local_session(session: RentalSession) -> RuntimeInstance:
    if not is_local_session(session):
        raise conflict(code="SESSION_NOT_LOCAL", message="This session does not use a local runtime.")
    return session.runtime_instance


async def claim_local_session(
    db: AsyncSession,
    session: RentalSession,
    *,
    request_id: str | None = None,
) -> tuple[RentalSession, AgentVersion]:
    """Device sidecar claims a local session. Does NOT extend expiry (expire_sessions owns it)."""
    runtime = ensure_local_session(session)
    await validate_session_active(session)
    if runtime.status in (RuntimeStatus.TERMINATED, RuntimeStatus.FAILED):
        raise session_expired(message="The local runtime for this session has ended.")

    version_result = await db.execute(
        select(AgentVersion).where(AgentVersion.id == runtime.agent_version_id)
    )
    version = version_result.scalar_one()

    now = datetime.now(UTC)
    if runtime.status != RuntimeStatus.RUNNING:
        runtime.status = RuntimeStatus.RUNNING
        runtime.started_at = now
    session.last_activity_at = now

    await write_audit_log(
        db,
        action="LOCAL_SESSION_CLAIMED",
        resource_type="session",
        resource_id=session.id,
        request_id=request_id,
    )
    return session, version


async def record_local_usage(
    db: AsyncSession,
    session: RentalSession,
    *,
    metric_type: str,
    quantity: float,
    unit: str,
    execution_id: UUID | None = None,
) -> UsageRecord:
    """Write a UsageRecord reported by the device sidecar (metering only, no document content)."""
    ensure_local_session(session)
    await validate_session_active(session)

    if execution_id is not None:
        exec_result = await db.execute(
            select(AgentExecution.id).where(
                AgentExecution.id == execution_id,
                AgentExecution.session_id == session.id,
            )
        )
        if exec_result.scalar_one_or_none() is None:
            raise bad_request(code="INVALID_EXECUTION", message="Execution not found for this session")

    now = datetime.now(UTC)
    record = UsageRecord(
        session_id=session.id,
        execution_id=execution_id,
        metric_type=metric_type,
        quantity=Decimal(str(quantity)),
        unit=unit,
        recorded_at=now,
    )
    db.add(record)
    session.last_activity_at = now
    await db.flush()
    return record


async def execute_agent(
    db: AsyncSession,
    session: RentalSession,
    *,
    input_data: str | dict,
    context: dict,
    request_id: str | None,
) -> AgentExecution:
    await validate_session_active(session)

    if is_local_session(session):
        raise bad_request(
            code="RUNTIME_LOCAL",
            message="This session runs on the renter's device via the local runtime; "
            "cloud execution is not available.",
        )

    session.last_activity_at = datetime.now(UTC)
    runtime = session.runtime_instance
    if not runtime or runtime.status != RuntimeStatus.RUNNING:
        raise bad_request(code="RUNTIME_NOT_READY", message="Runtime is not ready")

    execution = AgentExecution(
        session_id=session.id,
        agent_version_id=runtime.agent_version_id,
        status=ExecutionStatus.RUNNING,
        input_metadata={"input": input_data, "context": context},
        request_id=request_id or secrets.token_hex(8),
    )
    db.add(execution)
    await db.flush()

    start = datetime.now(UTC)
    output = await _invoke_runtime(db, session, runtime, input_data, context, request_id)
    duration_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)

    if output.get("status") == "waiting_for_approval":
        from app.services.approval import create_approval_request
        approval_data = output.get("approval", {})
        await create_approval_request(
            db,
            session=session,
            execution=execution,
            action_type=output.get("action", "UNKNOWN"),
            title=approval_data.get("title", "Approval Required"),
            description=approval_data.get("description", "Agent requires your approval."),
            details=approval_data.get("details"),
        )
        execution.duration_ms = duration_ms
        execution.usage_summary = output.get("usage", {})
        execution.output_metadata = output
        return execution

    execution.status = ExecutionStatus.COMPLETED
    execution.output_metadata = output
    execution.usage_summary = output.get("usage", {})
    execution.duration_ms = duration_ms
    execution.completed_at = datetime.now(UTC)

    db.add(UsageRecord(
        session_id=session.id,
        execution_id=execution.id,
        metric_type="requests",
        quantity=1,
        unit="count",
    ))
    if output.get("usage", {}).get("input_tokens"):
        db.add(UsageRecord(
            session_id=session.id,
            execution_id=execution.id,
            metric_type="input_tokens",
            quantity=output["usage"]["input_tokens"],
            unit="tokens",
        ))

    return execution


async def _invoke_runtime(
    db: AsyncSession,
    session: RentalSession,
    runtime: RuntimeInstance,
    input_data: str | dict,
    context: dict,
    request_id: str | None,
) -> dict:
    # Try runtime manager first (e.g. for specialized Docker agents)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.runtime_manager_url}/runtimes/{runtime.id}/invoke",
                json={"input": input_data, "context": context},
                headers={"X-Request-ID": request_id or ""},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass

    # Extract user message
    text = input_data if isinstance(input_data, str) else str(input_data.get("message", input_data))

    approval_response = _high_risk_approval_response(text)
    if approval_response:
        return approval_response

    # Execute via LLM service (Ollama -> Gemini -> OpenAI -> Smart Fallback)
    from app.services.llm import call_llm
    agent_version = session.rental.agent_version
    manifest = agent_version.manifest or {}
    system_prompt = manifest.get("system_prompt", "You are a helpful assistant.")
    
    # Extract onboarding answers from context
    onboarding_answers = context.get("onboarding", {})
    
    # Inject Vault Credentials
    from app.models import VaultCredential
    from sqlalchemy import select
    
    vault_creds = await db.execute(
        select(VaultCredential).where(VaultCredential.user_id == session.rental.customer.user_id)
    )
    creds = vault_creds.scalars().all()
    
    if creds:
        onboarding_answers["Connected Services"] = ", ".join([c.provider for c in creds])
        
    # Extract history
    history = session.context_metadata.get("history", []) if session.context_metadata else []
    
    llm_response = await call_llm(system_prompt, text, onboarding_answers, history)
    
    reply = llm_response.get("output", "")

    # Update history
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})

    # Keep only last 10 turns (20 messages)
    if len(history) > 20:
        history = history[-20:]

    if not session.context_metadata:
        session.context_metadata = {}

    # Update the context metadata dictionary. SQLAlchemy JSONB requires replacing the dict.
    new_metadata = dict(session.context_metadata)
    new_metadata["history"] = history
    session.context_metadata = new_metadata
        
    return {
        "status": "completed",
        "output": reply,
        "usage": llm_response.get("usage", {})
    }

    # Fallback to mock responses
    return _mock_agent_response(runtime, input_data)


def _high_risk_approval_response(text: str) -> dict | None:
    lower = text.lower()
    high_risk = {
        "send email": ("SEND_EMAIL", "Send Email", "Agent wants to send an email on your behalf."),
        "delete record": ("DELETE_RECORD", "Delete Record", "Agent wants to delete a record."),
        "execute payment": ("EXECUTE_PAYMENT", "Execute Payment", "Agent wants to process a payment."),
        "purchase order": ("CREATE_PURCHASE_ORDER", "Create Purchase Order", "Agent wants to create a purchase order."),
    }
    for keyword, (action, title, desc) in high_risk.items():
        if keyword in lower:
            return {
                "status": "waiting_for_approval",
                "action": action,
                "approval": {"title": title, "description": desc, "details": {"input_preview": text[:200]}},
                "usage": {"input_tokens": 20, "output_tokens": 0},
            }
    return None


def _mock_agent_response(runtime: RuntimeInstance, input_data: str | dict) -> dict:
    text = input_data if isinstance(input_data, str) else str(input_data.get("message", input_data))
    lower = text.lower()

    approval_response = _high_risk_approval_response(text)
    if approval_response:
        return approval_response

    if "invoice" in lower or "supplier" in lower or "pdf" in lower:
        return {
            "status": "completed",
            "output": {
                "supplier": "Acme Supplies Ltd",
                "invoice_number": "INV-2026-0847",
                "amount": "$4,250.00",
                "tax": "$637.50",
                "due_date": "2026-09-15",
                "anomalies": ["Line item quantity exceeds PO by 15%"],
            },
            "usage": {"input_tokens": 120, "output_tokens": 85},
        }
    if "maintenance" in lower or "laptop" in lower or "asset" in lower:
        return {
            "status": "completed",
            "output": {
                "assets": [
                    {"id": "LT-001", "name": "Dell Latitude 5540", "assigned_to": "John M.", "maintenance_due": "2026-08-20"},
                    {"id": "LT-007", "name": "MacBook Pro 14", "assigned_to": "Sarah K.", "maintenance_due": "2026-08-18"},
                ],
                "recommendation": "Schedule maintenance for 2 laptops this week.",
            },
            "usage": {"input_tokens": 95, "output_tokens": 110},
        }
    if "research" in lower or "fintech" in lower or "market" in lower:
        return {
            "status": "completed",
            "output": {
                "summary": "Kenyan fintech market growing at 22% CAGR",
                "competitors": ["M-Pesa", "Tala", "Branch", "Pezesha"],
                "trends": ["Embedded finance", "SME lending", "Cross-border payments"],
                "recommendations": ["Focus on B2B invoice financing", "Partner with telcos"],
            },
            "usage": {"input_tokens": 80, "output_tokens": 150},
        }
    if "resume" in lower or "candidate" in lower:
        return {
            "status": "completed",
            "output": {"score": 78, "strengths": ["Python", "FastAPI", "5yr experience"], "weaknesses": ["No K8s experience"], "recommendation": "Proceed to interview"},
            "usage": {"input_tokens": 200, "output_tokens": 60},
        }
    if "support" in lower or "customer" in lower or "question" in lower:
        return {
            "status": "completed",
            "output": {"response": "Thank you for reaching out. I've reviewed your account and can confirm your issue has been escalated to our technical team. You should receive an update within 24 hours."},
            "usage": {"input_tokens": 50, "output_tokens": 40},
        }

    return {
        "status": "completed",
        "output": f"Processed your request: {text[:200]}",
        "usage": {"input_tokens": 30, "output_tokens": 20},
    }


async def expire_session(db: AsyncSession, session: RentalSession) -> None:
    session.status = SessionStatus.EXPIRED

    if session.runtime_instance_id:
        runtime_result = await db.execute(
            select(RuntimeInstance).where(RuntimeInstance.id == session.runtime_instance_id)
        )
        runtime = runtime_result.scalar_one_or_none()
        if runtime and runtime.status not in (RuntimeStatus.TERMINATED, RuntimeStatus.FAILED):
            await _destroy_runtime(db, runtime)

    creds = await db.execute(
        select(AgentCredential).where(
            AgentCredential.session_id == session.id,
            AgentCredential.revoked_at.is_(None),
        )
    )
    for cred in creds.scalars():
        cred.revoked_at = datetime.now(UTC)

    await write_audit_log(
        db,
        action="SESSION_EXPIRED",
        resource_type="session",
        resource_id=session.id,
    )


async def _destroy_runtime(db: AsyncSession, runtime: RuntimeInstance) -> None:
    if runtime.runtime_provider != LOCAL_RUNTIME_PROVIDER:  # local runtimes never touch runtime-manager
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.delete(f"{settings.runtime_manager_url}/runtimes/{runtime.id}")
        except Exception:
            pass
    runtime.status = RuntimeStatus.TERMINATED
    runtime.terminated_at = datetime.now(UTC)
    await write_audit_log(
        db,
        action="RUNTIME_DESTROYED",
        resource_type="runtime",
        resource_id=runtime.id,
    )


async def extend_session(
    db: AsyncSession,
    session: RentalSession,
    customer: CustomerProfile,
    duration_minutes: int,
) -> RentalSession:
    await validate_session_active(session)

    rental = session.rental
    plan_result = await db.execute(
        select(AgentPricingPlan).where(AgentPricingPlan.id == rental.pricing_plan_id)
    )
    plan = plan_result.scalar_one()
    cost = _calculate_cost(plan.price_minor, plan.pricing_model, duration_minutes)

    await billing_provider.charge(
        db,
        customer_id=customer.id,
        gross_amount_minor=cost,
        currency=plan.currency,
        rental_id=rental.id,
        session_id=session.id,
        idempotency_key=f"extend_{session.id}_{duration_minutes}_{int(datetime.now(UTC).timestamp())}",
        transaction_type=TransactionType.EXTENSION,
    )

    session.expires_at += timedelta(minutes=duration_minutes)
    rental.expires_at = session.expires_at
    session.last_activity_at = datetime.now(UTC)

    return session

