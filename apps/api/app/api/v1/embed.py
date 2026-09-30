from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.embed_deps import RequireEmbedSession
from app.schemas.embed import (
    EmbedBootstrapResponse,
    EmbedChatRequest,
    EmbedChatResponse,
    EmbedOnboardingRequest,
    EmbedOnboardingResponse,
    EmbedSnippetResponse,
)
from app.services import embed as embed_service

router = APIRouter(prefix="/embed", tags=["embed"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _web_base_url(request: Request) -> str:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    from app.config import settings

    if settings.cors_origin_list:
        return settings.cors_origin_list[0].rstrip("/")
    return str(request.base_url).replace(":8000", ":3000").rstrip("/")


@router.get("/bootstrap", response_model=EmbedBootstrapResponse)
async def embed_bootstrap(session: RequireEmbedSession, request: Request):
    data = await embed_service.bootstrap(session, _web_base_url(request))
    return EmbedBootstrapResponse(**{k: v for k, v in data.items() if k != "widget_url"})


@router.post("/onboarding", response_model=EmbedOnboardingResponse)
async def embed_onboarding(
    body: EmbedOnboardingRequest,
    session: RequireEmbedSession,
    db: DbSession,
):
    result = await embed_service.submit_onboarding(db, session, body.answers)
    await db.commit()
    return EmbedOnboardingResponse(**result)


@router.post("/chat", response_model=EmbedChatResponse)
async def embed_chat(
    body: EmbedChatRequest,
    session: RequireEmbedSession,
    db: DbSession,
    request: Request,
):
    result = await embed_service.chat(
        db,
        session,
        body.message,
        getattr(request.state, "request_id", None),
    )
    await db.commit()
    return EmbedChatResponse(**result)

@router.post("/rotate-key", response_model=EmbedSnippetResponse)
async def embed_rotate_key(
    session: RequireEmbedSession,
    db: DbSession,
    request: Request,
):
    from app.services.embed_key import create_embed_key
    from sqlalchemy import select
    from app.models import EmbedKey
    
    # Revoke old keys
    old_keys = await db.execute(select(EmbedKey).where(EmbedKey.session_id == session.id))
    for key in old_keys.scalars():
        key.is_active = False
        
    # Create new key
    new_key_obj, raw_key = await create_embed_key(db, session.id, label="Rotated widget")
    await db.commit()
    
    return EmbedSnippetResponse(**embed_service.build_embed_snippet(raw_key, _web_base_url(request)))


from fastapi import WebSocket, WebSocketDisconnect

@router.websocket("/ws/{embed_key}")
async def embed_websocket(websocket: WebSocket, embed_key: str, db: DbSession):
    await websocket.accept()
    from app.services.embed_key import get_session_for_embed_key
    from app.services.llm import stream_llm
    
    try:
        session = await get_session_for_embed_key(db, embed_key)
        agent_version = session.rental.agent_version
        manifest = agent_version.manifest or {}
        system_prompt = manifest.get("system_prompt", "You are a helpful assistant.")
        
        while True:
            data = await websocket.receive_text()
            async for chunk in stream_llm(system_prompt, data):
                await websocket.send_json({"type": "chunk", "content": chunk})
            await websocket.send_json({"type": "end"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})
        await websocket.close()

