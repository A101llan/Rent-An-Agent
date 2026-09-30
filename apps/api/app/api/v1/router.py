from fastapi import APIRouter

from app.api.v1 import admin, agents, approvals, auth, developer, embed, health, marketplace, rentals, vault

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(health.router)
api_router.include_router(marketplace.router)
api_router.include_router(agents.router)
api_router.include_router(developer.router)
api_router.include_router(rentals.router)
api_router.include_router(embed.router)
api_router.include_router(approvals.router)
api_router.include_router(admin.router)
api_router.include_router(vault.router, prefix="/vault", tags=["vault"])
