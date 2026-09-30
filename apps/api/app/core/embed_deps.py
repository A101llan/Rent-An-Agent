from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.models import RentalSession
from app.services.embed_key import get_session_for_embed_key

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def require_embed_session(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
    x_embed_key: Annotated[str | None, Header(alias="X-Embed-Key")] = None,
) -> RentalSession:
    raw_key = x_embed_key
    if not raw_key and authorization and authorization.lower().startswith("bearer "):
        raw_key = authorization.split(" ", 1)[1].strip()
    if not raw_key:
        from app.core.errors import unauthorized

        raise unauthorized(
            code="EMBED_KEY_REQUIRED",
            message="Provide embed API key via Authorization: Bearer or X-Embed-Key header",
        )
    return await get_session_for_embed_key(db, raw_key)


RequireEmbedSession = Annotated[RentalSession, Depends(require_embed_session)]
