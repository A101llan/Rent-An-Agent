"""Provider factory."""

import logging

from app.config import settings
from app.providers.base import RuntimeProvider
from app.providers.mock import MockRuntimeProvider

logger = logging.getLogger(__name__)


def get_provider() -> RuntimeProvider:
    if settings.runtime_provider == "docker":
        try:
            from app.providers.docker_provider import DockerRuntimeProvider
            logger.info("Using DockerRuntimeProvider")
            return DockerRuntimeProvider()
        except Exception as e:
            logger.warning("Docker unavailable, falling back to mock: %s", e)
    logger.info("Using MockRuntimeProvider")
    return MockRuntimeProvider()
