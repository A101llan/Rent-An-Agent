"""Seed development data."""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.security import hash_password
from app.models import (
    Agent,
    AgentArtifact,
    AgentCapability,
    AgentPermission,
    AgentPricingPlan,
    AgentReview,
    AgentStatus,
    AgentVersion,
    CustomerProfile,
    DeveloperProfile,
    DeveloperStatus,
    PricingModel,
    User,
    UserRole,
    VerificationStatus,
    VersionStatus,
)
from app.schemas.agents import LOCAL_RUNTIME_TYPE, AgentManifest

# Source of truth for the Meeting Notes local runtime block. The inline fallback is only used
# where the agents/ tree is absent (the apps/api Docker image copies apps/api only);
# tests/test_agent_schemas.py asserts the fallback and the seeded runtime match this file.
_SCRIPT_PARENTS = Path(__file__).resolve().parents
MEETING_NOTES_LOCAL_MANIFEST_PATH = (
    _SCRIPT_PARENTS[4] / "agents" / "meeting-notes-agent" / "manifest.local.json"
    if len(_SCRIPT_PARENTS) > 4
    else None
)
MEETING_NOTES_LOCAL_RUNTIME_FALLBACK = {
    "type": LOCAL_RUNTIME_TYPE,
    "entrypoint": "meeting-notes",
    "min_sidecar_version": "0.1.0",
}


def load_meeting_notes_local_runtime() -> dict:
    """runtime block from agents/meeting-notes-agent/manifest.local.json (fallback: inline copy)."""
    path = MEETING_NOTES_LOCAL_MANIFEST_PATH
    if path is not None and path.is_file():
        runtime = json.loads(path.read_text(encoding="utf-8-sig"))["runtime"]
    else:
        runtime = MEETING_NOTES_LOCAL_RUNTIME_FALLBACK
    return dict(runtime)


DEMO_AGENTS = [
    {
        "slug": "research-agent",
        "name": "Research Agent",
        "description": "Conducts market research and competitive analysis with structured reports.",
        "category": "research",
        "capabilities": ["market_research", "competitive_analysis", "trend_analysis"],
        "permissions": ["internet.read"],
        "price_minor": 200,
        "pricing_model": PricingModel.PER_HOUR,
        "system_prompt": "You are a Research Agent. Your job is to conduct market research and competitive analysis. You provide structured, data-driven reports.",
        "onboarding_questions": [
            {"id": "industry", "question": "What industry or market should I focus on?", "placeholder": "e.g. SaaS, fintech, healthcare"},
            {"id": "competitors", "question": "List your key competitors or companies to benchmark.", "placeholder": "e.g. Stripe, Braintree, Adyen"},
            {"id": "goal", "question": "What decision is this research supporting?", "placeholder": "e.g. entering a new market, pricing strategy"},
        ],
    },
    {
        "slug": "resume-screening-agent",
        "name": "Resume Screening Agent",
        "description": "Analyzes resumes against job descriptions with scoring and recommendations.",
        "category": "hr",
        "capabilities": ["resume_analysis", "candidate_scoring"],
        "permissions": ["files.read"],
        "price_minor": 150,
        "pricing_model": PricingModel.PER_TASK,
        "system_prompt": "You are a Resume Screening Agent. Your job is to analyze resumes against job descriptions, score candidates objectively, and provide actionable recommendations for hiring managers.",
        "onboarding_questions": [
            {"id": "job_title", "question": "What job title or role are you hiring for?", "placeholder": "e.g. Senior Backend Engineer"},
            {"id": "must_haves", "question": "What are the non-negotiable requirements?", "placeholder": "e.g. 5+ years Python, remote-only, EU timezone"},
            {"id": "nice_to_haves", "question": "Any nice-to-have skills or traits?", "placeholder": "e.g. open source contributions, startup background"},
        ],
    },
    {
        "slug": "invoice-analyzer",
        "name": "Invoice Analyzer",
        "description": "Extracts invoice data from PDFs and detects anomalies.",
        "category": "finance",
        "capabilities": ["document_analysis", "invoice_extraction"],
        "permissions": ["files.read"],
        "price_minor": 200,
        "pricing_model": PricingModel.PER_HOUR,
        "system_prompt": "You are an Invoice Analyzer Agent. Your job is to extract structured data from invoices, detect anomalies, and flag potential fraud or errors for the finance team.",
        "onboarding_questions": [
            {"id": "company_name", "question": "What company or team will this agent support?", "placeholder": "e.g. Acme Finance AP team"},
            {"id": "erp_system", "question": "Which system do you process invoices in?", "placeholder": "e.g. QuickBooks, SAP, Excel"},
            {"id": "invoice_volume", "question": "Roughly how many invoices do you handle per week?", "placeholder": "e.g. 50–200"},
            {"id": "primary_goal", "question": "What should I focus on first?", "placeholder": "e.g. anomaly detection, data extraction, vendor matching"},
        ],
    },
    {
        "slug": "customer-support-agent",
        "name": "Customer Support Agent",
        "description": "Generates professional customer support responses.",
        "category": "support",
        "capabilities": ["customer_support", "response_generation"],
        "permissions": [],
        "price_minor": 100,
        "pricing_model": PricingModel.PER_REQUEST,
        "system_prompt": "You are a Customer Support Agent. Your job is to generate polite, professional, and helpful responses to customer inquiries.",
        "onboarding_questions": [
            {"id": "product_name", "question": "What product or service am I supporting?", "placeholder": "e.g. Acme SaaS platform"},
            {"id": "tone", "question": "What tone should I use in responses?", "placeholder": "e.g. formal and professional, friendly and casual"},
            {"id": "escalation_policy", "question": "When should I escalate to a human agent?", "placeholder": "e.g. billing disputes, legal complaints, angry VIPs"},
        ],
    },
    {
        "slug": "meeting-notes-agent",
        "name": "Meeting Notes Agent",
        "description": "Turns messy meeting notes or transcript snippets into structured summaries with decisions, action items, and open questions.",
        "category": "productivity",
        "capabilities": ["meeting_summarization", "action_item_extraction"],
        "permissions": [],
        "price_minor": 100,
        "pricing_model": PricingModel.PER_REQUEST,
        "system_prompt": "You are a Meeting Notes Agent. Your job is to take messy meeting notes or transcript snippets and return a structured summary with decisions, action items (owner + task), and open questions. Pure text in, structured JSON out.",
        "onboarding_questions": [
            {"id": "meeting_type", "question": "What type of meetings will I summarize?", "placeholder": "e.g. standup, product planning, client call"},
            {"id": "output_format", "question": "Preferred output format?", "placeholder": "e.g. JSON with decisions/action_items/open_questions"},
            {"id": "team_names", "question": "Any recurring attendees or role names to recognize?", "placeholder": "e.g. Alex (PM), Jordan (Eng)"},
        ],
    },
    {
        # Same agent as meeting-notes-agent, hired against the renter's local Windows
        # sidecar (apps/local-runtime) instead of the server runtime-manager.
        "slug": "meeting-notes-agent-local",
        "name": "Meeting Notes Agent (Local)",
        "description": "Runs on your own Windows device via the AgentHub local runtime. Turns messy meeting notes or transcript snippets into structured summaries with decisions, action items, and open questions.",
        "category": "productivity",
        "capabilities": ["meeting_summarization", "action_item_extraction"],
        "permissions": [],
        "price_minor": 100,
        "pricing_model": PricingModel.PER_REQUEST,
        "runtime": load_meeting_notes_local_runtime(),
        "system_prompt": "You are a Meeting Notes Agent. Your job is to take messy meeting notes or transcript snippets and return a structured summary with decisions, action items (owner + task), and open questions. Pure text in, structured JSON out.",
        "onboarding_questions": [
            {"id": "meeting_type", "question": "What type of meetings will I summarize?", "placeholder": "e.g. standup, product planning, client call"},
            {"id": "output_format", "question": "Preferred output format?", "placeholder": "e.g. JSON with decisions/action_items/open_questions"},
            {"id": "team_names", "question": "Any recurring attendees or role names to recognize?", "placeholder": "e.g. Alex (PM), Jordan (Eng)"},
        ],
    },
    {
        "slug": "asset-management-agent",
        "name": "Asset Management Agent",
        "description": "Manages and queries structured business asset data including maintenance tracking.",
        "category": "operations",
        "capabilities": ["asset_tracking", "maintenance_scheduling", "depreciation_analysis"],
        "permissions": ["database.read"],
        "price_minor": 250,
        "pricing_model": PricingModel.PER_HOUR,
        "system_prompt": "You are an Asset Management Agent. Your job is to help operations teams manage structured business asset data, track maintenance schedules, and analyze depreciation.",
        "onboarding_questions": [
            {"id": "asset_types", "question": "What types of assets are you tracking?", "placeholder": "e.g. laptops, vehicles, machinery"},
            {"id": "tracking_system", "question": "Do you have an existing asset tracking system?", "placeholder": "e.g. Snipe-IT, spreadsheet, ServiceNow"},
            {"id": "priority_task", "question": "What's the most urgent task you need help with?", "placeholder": "e.g. overdue maintenance alerts, depreciation reports"},
        ],
    },
]

SEED_USERS = [
    {"email": "admin@agenthub.dev", "password": "Admin123!", "role": UserRole.ADMIN, "display_name": "Admin User"},
    {"email": "dev@agenthub.dev", "password": "Dev123!", "role": UserRole.DEVELOPER, "display_name": "Demo Developer"},
    {"email": "customer@agenthub.dev", "password": "Customer123!", "role": UserRole.CUSTOMER, "display_name": "Demo Customer"},
]


def build_manifest(agent_data: dict) -> dict:
    """Manifest for a seeded agent; validated against the API's AgentManifest schema.

    Agents without an explicit "runtime" get a docker image/digest (server runtime).
    """
    runtime = dict(agent_data.get("runtime") or {
        "type": "docker",
        "image": f"agenthub/{agent_data['slug']}",
        "digest": f"sha256:{uuid.uuid4().hex}",
    })
    manifest = {
        "name": agent_data["name"],
        "version": "1.0.0",
        "runtime": runtime,
        "capabilities": agent_data["capabilities"],
        "permissions": agent_data["permissions"],
        "resources": {"cpu": 1, "memory_mb": 1024, "timeout_seconds": 300},
        "system_prompt": agent_data.get("system_prompt", "You are a helpful assistant."),
        "onboarding": {
            "questions": agent_data.get("onboarding_questions", []),
        },
    }
    AgentManifest.model_validate(manifest)
    return manifest


def build_artifact(agent_data: dict, version_id: uuid.UUID, manifest: dict) -> AgentArtifact | None:
    """Container artifact for server-runtime agents; local-runtime agents have none."""
    if manifest["runtime"]["type"] == LOCAL_RUNTIME_TYPE:
        return None
    return AgentArtifact(
        agent_version_id=version_id,
        image_registry="registry.agenthub.dev",
        image_name=f"agents/{agent_data['slug']}",
        image_digest=manifest["runtime"]["digest"],
        verification_status=VerificationStatus.PASSED,
        verified_at=datetime.now(UTC),
    )


async def seed() -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        existing = await db.execute(select(User).where(User.email == SEED_USERS[0]["email"]))
        if existing.scalar_one_or_none():
            print("Seed data already exists, skipping.")
            return

        developer_profile = None
        customer_profile = None
        for user_data in SEED_USERS:
            user = User(
                email=user_data["email"],
                password_hash=hash_password(user_data["password"]),
                role=user_data["role"],
                is_verified=True,
                is_active=True,
            )
            db.add(user)
            await db.flush()

            if user_data["role"] == UserRole.DEVELOPER:
                developer_profile = DeveloperProfile(
                    user_id=user.id,
                    display_name=user_data["display_name"],
                    company_name="AgentHub Labs",
                    status=DeveloperStatus.APPROVED,
                    approved_at=datetime.now(UTC),
                )
                db.add(developer_profile)
            elif user_data["role"] == UserRole.CUSTOMER:
                customer_profile = CustomerProfile(user_id=user.id, display_name=user_data["display_name"])
                db.add(customer_profile)

        await db.flush()

        if developer_profile:
            for agent_data in DEMO_AGENTS:
                agent = Agent(
                    developer_id=developer_profile.id,
                    slug=agent_data["slug"],
                    name=agent_data["name"],
                    description=agent_data["description"],
                    category=agent_data["category"],
                    status=AgentStatus.PUBLISHED,
                    is_featured=agent_data["slug"] == "invoice-analyzer",
                    is_verified=True,
                    avg_rating=4.5,
                    review_count=4,
                    published_at=datetime.now(UTC),
                )
                db.add(agent)
                await db.flush()

                manifest = build_manifest(agent_data)

                version = AgentVersion(
                    agent_id=agent.id,
                    version="1.0.0",
                    manifest=manifest,
                    runtime_requirements={"cpu": 1, "memory_mb": 1024},
                    status=VersionStatus.VERIFIED,
                )
                db.add(version)
                await db.flush()

                artifact = build_artifact(agent_data, version.id, manifest)
                if artifact is not None:
                    db.add(artifact)

                for cap in agent_data["capabilities"]:
                    db.add(AgentCapability(agent_version_id=version.id, capability=cap))

                for perm in agent_data["permissions"]:
                    db.add(AgentPermission(agent_version_id=version.id, permission=perm))

                db.add(AgentPricingPlan(
                    agent_version_id=version.id,
                    name="Standard",
                    pricing_model=agent_data["pricing_model"],
                    price_minor=agent_data["price_minor"],
                    currency="USD",
                    duration_minutes=30 if agent_data["pricing_model"] == PricingModel.PER_HOUR else None,
                ))

            # Seed reviews (one per agent from demo customer)
            if customer_profile:
                review_texts = {
                    "research-agent": (5, "Excellent research", "Saved hours on market analysis."),
                    "resume-screening-agent": (4, "Very useful", "Great for our hiring pipeline."),
                    "invoice-analyzer": (5, "Highly recommend", "Invoice extraction is spot-on."),
                    "customer-support-agent": (4, "Good value", "Professional responses every time."),
                    "meeting-notes-agent": (5, "Saves time", "Clean decisions and action items every time."),
                    "meeting-notes-agent-local": (5, "Private and fast", "Notes never leave my laptop."),
                    "asset-management-agent": (5, "Perfect", "Asset tracking is incredibly polished."),
                }
                agents_result = await db.execute(select(Agent))
                for agent in agents_result.scalars().all():
                    if agent.slug in review_texts:
                        rating, title, body = review_texts[agent.slug]
                        db.add(AgentReview(
                            agent_id=agent.id,
                            customer_id=customer_profile.id,
                            rating=rating,
                            title=title,
                            body=body,
                        ))

        await db.commit()
        print("Seed data created successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
