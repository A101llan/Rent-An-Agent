from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models import AgentStatus, PricingModel, VersionStatus

class OnboardingQuestion(BaseModel):
    id: str
    question: str
    placeholder: str | None = None

class OnboardingConfig(BaseModel):
    questions: list[OnboardingQuestion] = []

# manifest.runtime.type value for agents that run on the renter's device via the
# local-runtime sidecar (apps/local-runtime) instead of the server runtime-manager.
LOCAL_RUNTIME_TYPE = "local"
LOCAL_ONLY_RUNTIME_FIELDS = ("entrypoint", "min_sidecar_version")


class RuntimeRequirement(BaseModel):
    type: str = "docker"
    # Server/container runtimes (any type other than "local"): image + digest required.
    image: str | None = None
    digest: str | None = None
    # Local runtime only: sidecar job route (POST /jobs/{entrypoint}) and the
    # minimum sidecar version reported by its GET /health.
    entrypoint: str | None = None
    min_sidecar_version: str | None = None

    @property
    def is_local(self) -> bool:
        return self.type == LOCAL_RUNTIME_TYPE

    @model_validator(mode="after")
    def check_runtime_fields(self) -> "RuntimeRequirement":
        if self.is_local:
            return self
        missing = [f for f in ("image", "digest") if getattr(self, f) is None]
        if missing:
            raise ValueError(
                f"runtime.{' and runtime.'.join(missing)} required for runtime.type '{self.type}'"
            )
        local_only = [f for f in LOCAL_ONLY_RUNTIME_FIELDS if getattr(self, f) is not None]
        if local_only:
            raise ValueError(
                f"runtime.{', runtime.'.join(local_only)} only allowed for runtime.type "
                f"'{LOCAL_RUNTIME_TYPE}'"
            )
        return self


class AgentManifest(BaseModel):
    name: str | None = None
    version: str | None = None
    system_prompt: str | None = None
    runtime: RuntimeRequirement | None = None
    capabilities: list[str] = []
    permissions: list[str] = []
    onboarding: OnboardingConfig | None = None
    
    model_config = {"extra": "allow"}

class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    pages: int


class PricingPlanResponse(BaseModel):
    id: UUID
    name: str
    pricing_model: PricingModel
    price_minor: int
    currency: str
    duration_minutes: int | None

    model_config = {"from_attributes": True}


class AgentListItem(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    category: str
    icon_url: str | None
    is_featured: bool
    is_verified: bool
    avg_rating: float
    review_count: int
    developer_name: str | None = None
    starting_price_minor: int | None = None
    pricing_model: PricingModel | None = None
    capabilities: list[str] = []


class AgentDetailResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    category: str
    icon_url: str | None
    status: AgentStatus
    is_featured: bool
    is_verified: bool
    avg_rating: float
    review_count: int
    developer_name: str | None
    developer_company: str | None
    version: str | None
    capabilities: list[str]
    permissions: list[str]
    pricing_plans: list[PricingPlanResponse]
    manifest: dict | None = None
    published_at: datetime | None


class ReviewResponse(BaseModel):
    id: UUID
    rating: int
    title: str | None
    body: str | None
    customer_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateAgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9-]+$")
    description: str = Field(min_length=10)
    category: str = Field(min_length=1, max_length=100)


class CreateVersionRequest(BaseModel):
    version: str = Field(default="1.0.0")
    manifest: AgentManifest
    image_registry: str = "registry.agenthub.dev"
    # Required unless manifest.runtime.type == "local" (see check_image_for_runtime).
    image_name: str | None = None
    image_digest: str | None = None
    capabilities: list[str] = []
    permissions: list[str] = []
    pricing_model: PricingModel = PricingModel.PER_HOUR
    price_minor: int = Field(ge=0)
    duration_minutes: int | None = 30

    @model_validator(mode="after")
    def check_image_for_runtime(self) -> "CreateVersionRequest":
        runtime = self.manifest.runtime
        if runtime is not None and runtime.is_local:
            return self
        if self.image_name is None or self.image_digest is None:
            raise ValueError(
                "image_name and image_digest are required unless manifest.runtime.type "
                f"is '{LOCAL_RUNTIME_TYPE}'"
            )
        return self


class DeveloperAgentResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    status: AgentStatus
    avg_rating: float
    review_count: int
    is_verified: bool
    created_at: datetime
    latest_version: str | None

    model_config = {"from_attributes": True}


class DeveloperStatsResponse(BaseModel):
    published_agents: int
    active_rentals: int
    total_executions: int
    total_revenue_minor: int
    avg_rating: float
