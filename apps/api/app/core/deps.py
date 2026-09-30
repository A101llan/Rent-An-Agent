import uuid
from datetime import UTC, datetime
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.errors import forbidden, unauthorized
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User, UserRole

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True, protocol=2)
    return _redis


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise unauthorized()

    token = auth_header.split(" ", 1)[1]
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise unauthorized(code="INVALID_TOKEN", message="Invalid or expired token")

    user_id = uuid.UUID(payload["sub"])
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.developer_profile),
            selectinload(User.customer_profile),
        )
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise unauthorized(message="User account is inactive")

    if user.locked_until and user.locked_until > datetime.now(UTC):
        raise unauthorized(code="ACCOUNT_LOCKED", message="Account is temporarily locked")

    return user


async def get_optional_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    try:
        return await get_current_user(request, db)
    except Exception:
        return None


def require_role(*roles: UserRole):
    async def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise forbidden(message=f"Requires one of: {', '.join(r.value for r in roles)}")
        return user

    return checker


RequireAdmin = Annotated[User, Depends(require_role(UserRole.ADMIN))]
RequireDeveloper = Annotated[User, Depends(require_role(UserRole.DEVELOPER, UserRole.ADMIN))]
RequireCustomer = Annotated[User, Depends(require_role(UserRole.CUSTOMER, UserRole.ADMIN))]
CurrentUser = Annotated[User, Depends(get_current_user)]
