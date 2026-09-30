from abc import ABC, abstractmethod
from typing import Any


class ExecutionContext:
    def __init__(self, session_id: str, permissions: list[str]):
        self.session_id = session_id
        self.permissions = permissions

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


class Agent(ABC):
    """Base class for AgentHub marketplace agents."""

    @abstractmethod
    async def run(self, request: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        """Execute the agent with the given request and session context."""
        ...
