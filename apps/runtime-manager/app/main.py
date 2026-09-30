import os
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.providers.base import RuntimeSpec
from app.providers.factory import get_provider
from app.telemetry import setup_telemetry

provider = get_provider()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    runtimes = getattr(provider, "_runtimes", {}) or getattr(provider, "_containers", {})
    for rid in list(runtimes.keys()):
        rt = runtimes[rid]
        cid = rt.get("container_id", rid) if isinstance(rt, dict) else rid
        try:
            await provider.destroy(cid if isinstance(cid, str) else str(rid))
        except Exception:
            pass


app = FastAPI(title="AgentHub Runtime Manager", version="0.2.0", lifespan=lifespan)
setup_telemetry(app)


class CreateRuntimeRequest(BaseModel):
    runtime_id: str
    session_id: str
    manifest: dict


class InvokeRequest(BaseModel):
    input: str | dict
    context: dict = {}


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "runtime-manager",
        "provider": settings.runtime_provider,
    }


@app.get("/ready")
async def ready():
    if settings.runtime_provider == "docker":
        try:
            import docker
            docker.from_env().ping()
            return {"status": "ready", "provider": "docker", "docker": "ok"}
        except Exception as e:
            return {"status": "degraded", "provider": "docker", "docker": str(e)}
    return {"status": "ready", "provider": settings.runtime_provider}


@app.post("/runtimes")
async def create_runtime(body: CreateRuntimeRequest):
    spec = RuntimeSpec(
        runtime_id=body.runtime_id,
        session_id=body.session_id,
        manifest=body.manifest,
        cpu_limit=body.manifest.get("resources", {}).get("cpu", 1),
        memory_limit_mb=body.manifest.get("resources", {}).get("memory_mb", 1024),
        network_policy=body.manifest.get("network_policy", "none"),
    )
    info = await provider.create(spec)
    return {"identifier": info.identifier, "status": info.status, "endpoint": info.endpoint}


@app.get("/runtimes/{runtime_id}")
async def get_runtime(runtime_id: UUID):
    info = await provider.status(str(runtime_id))
    if info.status == "terminated":
        raise HTTPException(status_code=404, detail="Runtime not found")
    return {"identifier": info.identifier, "status": info.status}


@app.post("/runtimes/{runtime_id}/invoke")
async def invoke(runtime_id: UUID, body: InvokeRequest):
    result = await provider.execute(str(runtime_id), {"input": body.input, "context": body.context})
    return result


@app.delete("/runtimes/{runtime_id}")
async def destroy_runtime(runtime_id: UUID):
    await provider.destroy(str(runtime_id))
    return {"status": "terminated"}


@app.post("/internal/{runtime_id}/invoke")
async def internal_invoke(runtime_id: UUID, body: InvokeRequest):
    raise HTTPException(status_code=403, detail="Internal endpoint not accessible")
