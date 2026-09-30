"""Session-scoped access for renters integrating via API."""

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_optional_user
from app.core.errors import not_found, unauthorized
from app.core.security import hash_token
from app.models import RentalSession, User
from app.services import rental as rental_service

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def require_session_access(
    session_id: UUID,
    request: Request,
    db: DbSession,
    user: Annotated[User | None, Depends(get_optional_user)] = None,
    x_session_token: Annotated[str | None, Header(alias="X-Session-Token")] = None,
) -> RentalSession:
    """Allow JWT (session owner) or X-Session-Token scoped to this session."""
    if x_session_token:
        return await rental_service.get_session_by_token(db, session_id, x_session_token)

    if user:
        customer = await rental_service.get_customer_for_user(db, user.id)
        return await rental_service.get_session_for_user(db, session_id, customer)

    raise unauthorized(message="Provide Bearer token or X-Session-Token")


RequireSession = Annotated[RentalSession, Depends(require_session_access)]


async def require_session_access_strict(
    session_id: UUID,
    request: Request,
    db: DbSession,
    user: Annotated[User | None, Depends(get_optional_user)] = None,
    x_session_token: Annotated[str | None, Header(alias="X-Session-Token")] = None,
) -> RentalSession:
    """Fail-closed access for local-runtime endpoints using the agreed auth contract."""
    if x_session_token:
        # Do not reveal whether a session exists to token-authenticated callers.
        return await rental_service.get_session_by_token(db, session_id, x_session_token)

    if not user:
        raise unauthorized(message="Provide Bearer token or X-Session-Token")

    customer = await rental_service.get_customer_for_user(db, user.id)
    session = await rental_service.get_session_by_id(db, session_id)
    if session is None or session.rental.customer_id != customer.id:
        raise not_found(code="SESSION_NOT_FOUND", message="Session not found")
    return session


RequireSessionStrict = Annotated[RentalSession, Depends(require_session_access_strict)]
