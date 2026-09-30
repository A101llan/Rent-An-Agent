from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.audit import write_audit_log, write_security_event
from app.core.deps import CurrentUser, get_db, get_redis
from app.core.errors import bad_request, too_many_requests, unauthorized
from app.core.security import (
    create_access_token,
    create_refresh_token_value,
    hash_password,
    hash_token,
    verify_password,
)
from app.models import CustomerProfile, DeveloperProfile, RefreshToken, User, UserRole
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, TokenResponse, UserResponse
from datetime import UTC, datetime, timedelta

router = APIRouter(prefix="/auth", tags=["auth"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[aioredis.Redis, Depends(get_redis)]


async def _rate_limit(redis: aioredis.Redis, key: str, limit: int, window: int) -> None:
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window)
    if current > limit:
        raise too_many_requests()


def _user_response(user: User) -> UserResponse:
    display_name = None
    if user.developer_profile:
        display_name = user.developer_profile.display_name
    elif user.customer_profile:
        display_name = user.customer_profile.display_name
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        is_verified=user.is_verified,
        display_name=display_name,
        created_at=user.created_at,
    )


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    response: Response,
) -> AuthResponse:
    client_ip = request.client.host if request.client else "unknown"
    await _rate_limit(redis, f"rl:register:{client_ip}", limit=5, window=3600)

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise bad_request(code="EMAIL_EXISTS", message="Email already registered")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        is_verified=settings.environment == "development",
    )
    db.add(user)
    await db.flush()

    if body.role == UserRole.DEVELOPER:
        db.add(DeveloperProfile(
            user_id=user.id,
            display_name=body.display_name or body.email.split("@")[0],
        ))
    else:
        db.add(CustomerProfile(
            user_id=user.id,
            display_name=body.display_name or body.email.split("@")[0],
        ))

    access_token = create_access_token(str(user.id), user.role.value)
    refresh_value = create_refresh_token_value()
    refresh = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_value),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(refresh)

    request_id = getattr(request.state, "request_id", None)
    await write_audit_log(
        db, action="USER_REGISTERED", resource_type="user", resource_id=user.id,
        actor_id=user.id, request_id=request_id, ip_address=client_ip,
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_value,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 86400,
    )

    result = await db.execute(
        select(User)
        .options(
            selectinload(User.developer_profile),
            selectinload(User.customer_profile),
        )
        .where(User.id == user.id)
    )
    user = result.scalar_one()
    return AuthResponse(
        user=_user_response(user),
        tokens=TokenResponse(
            access_token=access_token,
            expires_in=settings.access_token_expire_minutes * 60,
        ),
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: DbSession,
    redis: RedisClient,
    response: Response,
) -> AuthResponse:
    client_ip = request.client.host if request.client else "unknown"
    await _rate_limit(redis, f"rl:login:{client_ip}", limit=10, window=300)

    result = await db.execute(
        select(User)
        .options(
            selectinload(User.developer_profile),
            selectinload(User.customer_profile),
        )
        .where(User.email == body.email)
    )
    user = result.scalar_one_or_none()
    request_id = getattr(request.state, "request_id", None)

    if not user or not verify_password(body.password, user.password_hash):
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.max_login_attempts:
                user.locked_until = datetime.now(UTC) + timedelta(minutes=settings.lockout_minutes)
            await write_security_event(
                db, event_type="LOGIN_FAILED", severity="warning",
                user_id=user.id if user else None,
                metadata={"email": body.email}, request_id=request_id,
            )
        raise unauthorized(code="INVALID_CREDENTIALS", message="Invalid email or password")

    if user.locked_until and user.locked_until > datetime.now(UTC):
        raise unauthorized(code="ACCOUNT_LOCKED", message="Account is temporarily locked")

    user.failed_login_attempts = 0
    user.locked_until = None

    access_token = create_access_token(str(user.id), user.role.value)
    refresh_value = create_refresh_token_value()
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_value),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
    ))

    await write_audit_log(
        db, action="LOGIN", resource_type="user", resource_id=user.id,
        actor_id=user.id, request_id=request_id, ip_address=client_ip,
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_value,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 86400,
    )

    return AuthResponse(
        user=_user_response(user),
        tokens=TokenResponse(
            access_token=access_token,
            expires_in=settings.access_token_expire_minutes * 60,
        ),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    db: DbSession,
    response: Response,
) -> TokenResponse:
    raw_token = request.cookies.get("refresh_token")
    if not raw_token:
        raise unauthorized(code="NO_REFRESH_TOKEN", message="Refresh token required")

    token_hash = hash_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
        )
    )
    stored = result.scalar_one_or_none()
    if not stored or stored.expires_at < datetime.now(UTC):
        raise unauthorized(code="INVALID_REFRESH_TOKEN", message="Invalid or expired refresh token")

    user_result = await db.execute(
        select(User)
        .options(
            selectinload(User.developer_profile),
            selectinload(User.customer_profile),
        )
        .where(User.id == stored.user_id)
    )
    user = user_result.scalar_one()
    if not user.is_active:
        raise unauthorized(message="User account is inactive")

    stored.revoked_at = datetime.now(UTC)

    new_refresh = create_refresh_token_value()
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_token(new_refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
    ))

    response.set_cookie(
        key="refresh_token",
        value=new_refresh,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 86400,
    )

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role.value),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout")
async def logout(
    request: Request,
    db: DbSession,
    response: Response,
    user: CurrentUser,
) -> dict:
    raw_token = request.cookies.get("refresh_token")
    if raw_token:
        token_hash = hash_token(raw_token)
        result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        stored = result.scalar_one_or_none()
        if stored:
            stored.revoked_at = datetime.now(UTC)

    response.delete_cookie("refresh_token")
    request_id = getattr(request.state, "request_id", None)
    await write_audit_log(
        db, action="LOGOUT", resource_type="user", resource_id=user.id,
        actor_id=user.id, request_id=request_id,
    )
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_me(user: CurrentUser) -> UserResponse:
    return _user_response(user)
