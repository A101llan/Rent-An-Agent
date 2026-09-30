from pydantic import BaseModel, Field


class EmbedBootstrapResponse(BaseModel):
    agent_name: str
    agent_slug: str
    session_id: str
    expires_at: str
    onboarding_complete: bool
    questions: list[dict[str, str]] = []
    welcome_message: str | None = None


class EmbedOnboardingRequest(BaseModel):
    answers: dict[str, str] = Field(description="Question id → answer")


class EmbedOnboardingResponse(BaseModel):
    onboarding_complete: bool
    welcome_message: str


class EmbedChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class EmbedChatResponse(BaseModel):
    execution_id: str
    status: str
    reply: str
    output: dict | str | None = None
    approval_id: str | None = None


class EmbedSnippetResponse(BaseModel):
    api_key: str
    embed_html: str
    embed_script: str
    demo_page_url: str
