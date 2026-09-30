"""In-process mock runtime for development without Docker."""

from typing import Any

from app.providers.base import RuntimeInfo, RuntimeProvider, RuntimeSpec
from app.agents.handlers import invoke_agent


class MockRuntimeProvider(RuntimeProvider):
    def __init__(self):
        self._runtimes: dict[str, dict] = {}

    async def create(self, spec: RuntimeSpec) -> RuntimeInfo:
        agent_name = spec.manifest.get("runtime", {}).get("image", "unknown").split("/")[-1]
        self._runtimes[spec.runtime_id] = {
            "identifier": spec.runtime_id,
            "status": "running",
            "agent_name": agent_name,
            "manifest": spec.manifest,
            "endpoint": f"mock://{spec.runtime_id}",
        }
        return RuntimeInfo(
            identifier=spec.runtime_id,
            status="running",
            endpoint=f"mock://{spec.runtime_id}",
        )

    async def start(self, identifier: str) -> RuntimeInfo:
        rt = self._runtimes.get(identifier, {})
        rt["status"] = "running"
        return RuntimeInfo(identifier=identifier, status="running")

    async def stop(self, identifier: str) -> None:
        if identifier in self._runtimes:
            self._runtimes[identifier]["status"] = "stopped"

    async def destroy(self, identifier: str) -> None:
        self._runtimes.pop(identifier, None)

    async def status(self, identifier: str) -> RuntimeInfo:
        rt = self._runtimes.get(identifier, {})
        return RuntimeInfo(
            identifier=identifier,
            status=rt.get("status", "terminated"),
        )

    async def execute(self, identifier: str, payload: dict[str, Any]) -> dict[str, Any]:
        rt = self._runtimes.get(identifier)
        if not rt:
            return {"status": "failed", "output": "Runtime not found"}
        agent_name = rt.get("agent_name", "")
        return invoke_agent(agent_name, payload)
