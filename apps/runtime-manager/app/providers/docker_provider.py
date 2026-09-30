"""Docker runtime provider with security constraints for untrusted agent workloads."""

import asyncio
import logging
from typing import Any

import httpx

from app.config import settings
from app.providers.base import RuntimeInfo, RuntimeProvider, RuntimeSpec

logger = logging.getLogger(__name__)

# Lazy import — docker SDK optional when using mock provider
_docker_client = None


def _get_docker_client():
    global _docker_client
    if _docker_client is None:
        import docker
        _docker_client = docker.from_env()
    return _docker_client


def _agent_slug_from_manifest(manifest: dict) -> str:
    image = manifest.get("runtime", {}).get("image", "unknown")
    return image.split("/")[-1].replace("-agent", "").replace("agent", "agent")


class DockerRuntimeProvider(RuntimeProvider):
    """Runs agent containers with least-privilege security settings."""

    def __init__(self):
        self._containers: dict[str, dict] = {}

    async def _run_sync(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _ensure_network(self, client):
        try:
            client.networks.get(settings.docker_network)
        except Exception:
            client.networks.create(
                settings.docker_network,
                driver="bridge",
                internal=False,
                options={"com.docker.network.bridge.enable_icc": "false"}
            )

    async def create(self, spec: RuntimeSpec) -> RuntimeInfo:
        client = _get_docker_client()
        await self._run_sync(self._ensure_network, client)

        container_name = f"agenthub-{spec.runtime_id[:12]}"
        agent_slug = _agent_slug_from_manifest(spec.manifest)

        host_config_kwargs = {
            "mem_limit": f"{spec.memory_limit_mb}m",
            "nano_cpus": int(spec.cpu_limit * 1e9),
            "read_only": True,
            "security_opt": ["no-new-privileges"],
            "cap_drop": ["ALL"],
            "pids_limit": 100,
        }

        if spec.network_policy == "none":
            host_config_kwargs["network_mode"] = "none"

        host_config = client.api.create_host_config(**host_config_kwargs)

        container = await self._run_sync(
            client.containers.create,
            image=settings.agent_image,
            name=container_name,
            environment={
                "AGENT_SLUG": agent_slug,
                "SESSION_ID": spec.session_id,
            },
            host_config=host_config,
            user="65534:65534",
            detach=True,
            labels={
                "agenthub.runtime_id": spec.runtime_id,
                "agenthub.session_id": spec.session_id,
                "agenthub.managed": "true",
            },
        )

        await self._run_sync(container.start)

        # Attach to network if not using network_mode none
        if spec.network_policy != "none":
            try:
                network = client.networks.get(settings.docker_network)
                await self._run_sync(network.connect, container.id)
            except Exception as e:
                logger.warning("Network connect: %s", e)

        await asyncio.sleep(1)  # wait for uvicorn startup

        container.reload()
        ip = self._get_container_ip(container, client)

        self._containers[spec.runtime_id] = {
            "container_id": container.id,
            "name": container_name,
            "endpoint": f"http://{ip}:8080" if ip else None,
            "status": "running",
            "agent_slug": agent_slug,
        }

        return RuntimeInfo(
            identifier=container.id,
            status="running",
            endpoint=self._containers[spec.runtime_id]["endpoint"],
            metadata={"container_name": container_name},
        )

    def _get_container_ip(self, container, client) -> str | None:
        try:
            if settings.docker_network != "none":
                network = client.networks.get(settings.docker_network)
                nets = container.attrs.get("NetworkSettings", {}).get("Networks", {})
                if settings.docker_network in nets:
                    return nets[settings.docker_network].get("IPAddress")
                if nets:
                    return next(iter(nets.values())).get("IPAddress")
            return container.attrs["NetworkSettings"]["IPAddress"] or None
        except Exception:
            return None

    async def start(self, identifier: str) -> RuntimeInfo:
        rt = self._find_by_container(identifier)
        if rt:
            client = _get_docker_client()
            container = client.containers.get(identifier)
            await self._run_sync(container.start)
            rt["status"] = "running"
        return RuntimeInfo(identifier=identifier, status="running")

    async def stop(self, identifier: str) -> None:
        try:
            client = _get_docker_client()
            container = client.containers.get(identifier)
            await self._run_sync(container.stop, timeout=10)
            rt = self._find_by_container(identifier)
            if rt:
                rt["status"] = "stopped"
        except Exception as e:
            logger.warning("Stop container %s: %s", identifier, e)

    async def destroy(self, identifier: str) -> None:
        runtime_id = self._find_runtime_id(identifier)
        try:
            client = _get_docker_client()
            container = client.containers.get(identifier)
            await self._run_sync(container.stop, timeout=5)
            await self._run_sync(container.remove, force=True)
        except Exception as e:
            logger.warning("Destroy container %s: %s", identifier, e)
        if runtime_id:
            self._containers.pop(runtime_id, None)

    async def status(self, identifier: str) -> RuntimeInfo:
        rt = self._find_by_container(identifier)
        if not rt:
            runtime_id = identifier if identifier in self._containers else None
            if runtime_id and runtime_id in self._containers:
                rt = self._containers[runtime_id]
            else:
                return RuntimeInfo(identifier=identifier, status="terminated")
        try:
            client = _get_docker_client()
            container = client.containers.get(rt["container_id"])
            state = container.status
            return RuntimeInfo(identifier=rt["container_id"], status=state)
        except Exception:
            return RuntimeInfo(identifier=identifier, status="terminated")

    async def execute(self, identifier: str, payload: dict[str, Any]) -> dict[str, Any]:
        rt = self._find_by_container(identifier) or self._containers.get(identifier)
        if not rt:
            return {"status": "failed", "output": "Runtime not found"}

        endpoint = rt.get("endpoint")
        if endpoint:
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.post(f"{endpoint}/invoke", json=payload)
                    if resp.status_code == 200:
                        return resp.json()
            except Exception as e:
                logger.warning("Container invoke failed: %s", e)

        # Fallback to in-process handler if container unreachable
        from app.agents.handlers import invoke_agent
        return invoke_agent(rt.get("agent_slug", ""), payload)

    def _find_by_container(self, container_id: str) -> dict | None:
        for rt in self._containers.values():
            if rt["container_id"] == container_id or rt.get("name") == container_id:
                return rt
        return None

    def _find_runtime_id(self, identifier: str) -> str | None:
        for rid, rt in self._containers.items():
            if rt["container_id"] == identifier or rid == identifier:
                return rid
        return None

    @property
    def _runtimes(self) -> dict:
        return self._containers
