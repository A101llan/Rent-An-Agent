from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    runtime_provider: str = "mock"  # mock | docker
    docker_network: str = "agenthub-agents"
    agent_image: str = "agenthub-demo-agent:latest"
    docker_host: str | None = None
    otel_endpoint: str | None = None
    otel_service_name: str = "runtime-manager"


settings = Settings()
