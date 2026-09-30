from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://agenthub:agenthub@localhost:5432/agenthub"
    database_url_sync: str = "postgresql://agenthub:agenthub@localhost:5432/agenthub"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    cors_origins: str = "http://localhost:3000"

    storage_endpoint: str = "http://localhost:9000"
    storage_access_key: str = "minioadmin"
    storage_secret_key: str = "minioadmin"
    storage_bucket: str = "agenthub"

    runtime_manager_url: str = "http://localhost:8001"
    platform_fee_bps: int = 2000
    default_currency: str = "USD"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:1b"

    gemini_api_key: str | None = None
    openai_api_key: str | None = None

    # Fernet key for vault credential encryption (base64-url-safe, 32 bytes).
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    vault_encryption_key: str = "CHANGE-ME-generate-a-real-fernet-key"
    # Comma-separated list of old Fernet keys for seamless rotation
    vault_encryption_key_previous: str | None = None

    max_login_attempts: int = 5
    lockout_minutes: int = 15

    otel_endpoint: str | None = None
    otel_service_name: str = "agenthub-api"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
