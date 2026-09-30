"""One-off: insert meeting-notes-agent and meeting-notes-agent-local if missing.

Does not wipe existing seed data; each slug is inserted only when absent. For an existing
meeting-notes-agent-local, the seeded version's stored manifest (AgentVersion.manifest, which
local claim returns) is refreshed to the current build_manifest() output. Idempotent: rerunning
with an up-to-date manifest changes nothing. No rows are ever deleted.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import (
    Agent,
    AgentCapability,
    AgentPermission,
    AgentPricingPlan,
    AgentStatus,
    AgentVersion,
    DeveloperProfile,
    PricingModel,
    User,
    UserRole,
    VersionStatus,
)
from app.scripts.seed import DEMO_AGENTS, build_artifact, build_manifest

AGENT = {
    "slug": "meeting-notes-agent",
    "name": "Meeting Notes Agent",
    "description": (
        "Turns messy meeting notes or transcript snippets into structured summaries "
        "with decisions, action items, and open questions."
    ),
    "category": "productivity",
    "capabilities": ["meeting_summarization", "action_item_extraction"],
    "permissions": [],
    "price_minor": 100,
    "pricing_model": PricingModel.PER_REQUEST,
    "system_prompt": (
        "You are a Meeting Notes Agent. Your job is to take messy meeting notes or "
        "transcript snippets and return a structured summary with decisions, action "
        "items (owner + task), and open questions. Pure text in, structured JSON out."
    ),
    "onboarding_questions": [
        {
            "id": "meeting_type",
            "question": "What type of meetings will I summarize?",
            "placeholder": "e.g. standup, product planning, client call",
        },
        {
            "id": "output_format",
            "question": "Preferred output format?",
            "placeholder": "e.g. JSON with decisions/action_items/open_questions",
        },
        {
            "id": "team_names",
            "question": "Any recurring attendees or role names to recognize?",
            "placeholder": "e.g. Alex (PM), Jordan (Eng)",
        },
    ],
}

# Local-runtime listing (manifest.runtime.type == "local"); defined once in seed.py.
AGENT_LOCAL = next(a for a in DEMO_AGENTS if a["slug"] == "meeting-notes-agent-local")

AGENTS = [AGENT, AGENT_LOCAL]

# Slugs whose existing seeded manifest is refreshed in place (never other agents' rows).
REFRESH_MANIFEST_SLUGS = {AGENT_LOCAL["slug"]}


async def refresh_manifest(db: AsyncSession, agent: Agent, agent_data: dict) -> bool:
    """Set the seeded version's manifest to build_manifest() if it differs. Returns True if changed."""
    manifest = build_manifest(agent_data)
    result = await db.execute(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id,
            AgentVersion.version == manifest["version"],
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        print(f"Agent {agent.slug}: no version {manifest['version']} to refresh — skipping.")
        return False
    if version.manifest == manifest:
        print(f"Agent {agent.slug}: manifest already up to date (runtime={manifest['runtime']}).")
        return False
    print(f"Agent {agent.slug}: runtime {version.manifest.get('runtime')} -> {manifest['runtime']}")
    version.manifest = manifest  # reassign (not mutate) so the JSONB change is flushed
    return True


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        missing = []
        refreshed = 0
        for agent_data in AGENTS:
            existing = await db.execute(select(Agent).where(Agent.slug == agent_data["slug"]))
            agent = existing.scalar_one_or_none()
            if agent is None:
                missing.append(agent_data)
            elif agent_data["slug"] in REFRESH_MANIFEST_SLUGS:
                refreshed += await refresh_manifest(db, agent, agent_data)
            else:
                print(f"Agent {agent_data['slug']} already exists — skipping.")
        if refreshed:
            await db.commit()
            print(f"Refreshed manifest for {refreshed} agent version(s).")
        if not missing:
            print("Nothing to insert.")
            await engine.dispose()
            return

        dev_user = await db.execute(select(User).where(User.email == "dev@agenthub.dev"))
        user = dev_user.scalar_one_or_none()
        if not user:
            print("dev@agenthub.dev not found — run full seed first.")
            await engine.dispose()
            return

        profile_result = await db.execute(
            select(DeveloperProfile).where(DeveloperProfile.user_id == user.id)
        )
        developer_profile = profile_result.scalar_one_or_none()
        if not developer_profile:
            print("Developer profile missing — run full seed first.")
            await engine.dispose()
            return

        for agent_data in missing:
            agent = Agent(
                developer_id=developer_profile.id,
                slug=agent_data["slug"],
                name=agent_data["name"],
                description=agent_data["description"],
                category=agent_data["category"],
                status=AgentStatus.PUBLISHED,
                is_featured=False,
                is_verified=True,
                avg_rating=4.8,
                review_count=0,
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

            db.add(
                AgentPricingPlan(
                    agent_version_id=version.id,
                    name="Standard",
                    pricing_model=agent_data["pricing_model"],
                    price_minor=agent_data["price_minor"],
                    currency="USD",
                    duration_minutes=None,
                )
            )
            print(f"Inserting published agent: {agent_data['slug']} (id={agent.id})")

        await db.commit()
        print(f"Inserted {len(missing)} agent(s).")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
