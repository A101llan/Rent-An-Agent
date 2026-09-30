import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import unauthorized
from app.core.security import hash_token
from app.models import AgentVersion, EmbedKey, Rental, RentalSession

EMBED_KEY_PREFIX = "ahk_live_"


def generate_embed_key() -> tuple[str, str, str]:
    """Return (raw_key, key_hash, display_prefix)."""
    secret = secrets.token_urlsafe(32)
    raw = f"{EMBED_KEY_PREFIX}{secret}"
    return raw, hash_token(raw), raw[:16]


async def create_embed_key(
    db: AsyncSession,
    session_id: UUID,
    *,
    label: str = "Embed widget",
) -> tuple[EmbedKey, str]:
    raw, key_hash, prefix = generate_embed_key()
    embed_key = EmbedKey(
        session_id=session_id,
        key_hash=key_hash,
        prefix=prefix,
        label=label,
    )
    db.add(embed_key)
    await db.flush()
    return embed_key, raw


async def get_session_for_embed_key(db: AsyncSession, raw_key: str) -> RentalSession:
    if not raw_key.startswith(EMBED_KEY_PREFIX):
        raise unauthorized(code="INVALID_EMBED_KEY", message="Invalid embed API key")

    key_hash = hash_token(raw_key)
    result = await db.execute(
        select(EmbedKey)
        .where(EmbedKey.key_hash == key_hash, EmbedKey.is_active.is_(True))
    )
    embed_key = result.scalar_one_or_none()
    if not embed_key:
        raise unauthorized(code="INVALID_EMBED_KEY", message="Invalid or revoked embed API key")

    embed_key.last_used_at = datetime.now(UTC)

    session_result = await db.execute(
        select(RentalSession)
        .options(
            selectinload(RentalSession.rental).selectinload(Rental.agent),
            selectinload(RentalSession.rental).selectinload(Rental.agent_version),
            selectinload(RentalSession.rental).selectinload(Rental.customer),
            selectinload(RentalSession.runtime_instance),
        )
        .where(RentalSession.id == embed_key.session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise unauthorized(code="INVALID_EMBED_KEY", message="Session not found for this key")
    return session
