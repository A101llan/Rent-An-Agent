import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def write_audit_log(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    metadata: dict | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> None:
    log = AuditLog(
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_=metadata,
        request_id=request_id,
        ip_address=ip_address,
    )
    db.add(log)


async def write_security_event(
    db: AsyncSession,
    *,
    event_type: str,
    severity: str = "info",
    user_id: uuid.UUID | None = None,
    metadata: dict | None = None,
    request_id: str | None = None,
) -> None:
    from app.models import SecurityEvent

    event = SecurityEvent(
        user_id=user_id,
        event_type=event_type,
        severity=severity,
        metadata_=metadata,
        request_id=request_id,
    )
    db.add(event)
