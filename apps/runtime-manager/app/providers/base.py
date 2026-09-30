"""Runtime provider abstraction."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeSpec:
    runtime_id: str
    session_id: str
    manifest: dict
    cpu_limit: int = 1
    memory_limit_mb: int = 1024
    network_policy: str = "none"


@dataclass
class RuntimeInfo:
    identifier: str
    status: str
    endpoint: str | None = None
    metadata: dict = field(default_factory=dict)


class RuntimeProvider(ABC):
    @abstractmethod
    async def create(self, spec: RuntimeSpec) -> RuntimeInfo:
        ...

    @abstractmethod
    async def start(self, identifier: str) -> RuntimeInfo:
        ...

    @abstractmethod
    async def stop(self, identifier: str) -> None:
        ...

    @abstractmethod
    async def destroy(self, identifier: str) -> None:
        ...

    @abstractmethod
    async def status(self, identifier: str) -> RuntimeInfo:
        ...

    @abstractmethod
    async def execute(self, identifier: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...
