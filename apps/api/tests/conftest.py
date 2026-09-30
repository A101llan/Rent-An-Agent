import os
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.models import (
    Agent,
    AgentPricingPlan,
    AgentStatus,
    AgentVersion,
    Base,
    CustomerProfile,
    DeveloperProfile,
    DeveloperStatus,
    PricingModel,
    User,
    UserRole,
    VersionStatus,
)
from app.core.security import hash_password, create_access_token
from app.db.session import get_db

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://agenthub:agenthub@localhost:5432/agenthub_test"
)


def error_body(response) -> dict:
    """Extract the API error envelope (detail.error per the local-runtime contract)."""
    body = response.json()
    if "error" in body:
        return body["error"]
    return body["detail"]["error"]


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(autouse=True)
async def reset_redis_client():
    """Avoid reusing a module-level async Redis client across per-test event loops."""
    import app.core.deps as deps

    if deps._redis is not None:
        try:
            await deps._redis.aclose()
        except Exception:
            pass
        deps._redis = None
    yield
    if deps._redis is not None:
        try:
            await deps._redis.aclose()
        except Exception:
            pass
        deps._redis = None


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        # rental_sessions <-> runtime_instances FKs form a cycle, so metadata.drop_all cannot
        # sort existing tables; drop them with CASCADE first (drop_all then only drops enum types).
        for table in Base.metadata.tables.values():
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seed_data(db_session):
    """Create two customers, developer, agent, pricing plan."""
    dev_user = User(
        email="dev@test.com", password_hash=hash_password("pass"), role=UserRole.DEVELOPER, is_verified=True
    )
    cust_a_user = User(
        email="customer_a@test.com", password_hash=hash_password("pass"), role=UserRole.CUSTOMER, is_verified=True
    )
    cust_b_user = User(
        email="customer_b@test.com", password_hash=hash_password("pass"), role=UserRole.CUSTOMER, is_verified=True
    )
    db_session.add_all([dev_user, cust_a_user, cust_b_user])
    await db_session.flush()

    dev_profile = DeveloperProfile(
        user_id=dev_user.id, display_name="Dev", status=DeveloperStatus.APPROVED,
        approved_at=datetime.now(UTC),
    )
    cust_a = CustomerProfile(user_id=cust_a_user.id, display_name="Customer A")
    cust_b = CustomerProfile(user_id=cust_b_user.id, display_name="Customer B")
    db_session.add_all([dev_profile, cust_a, cust_b])
    await db_session.flush()

    agent = Agent(
        developer_id=dev_profile.id, slug="test-agent", name="Test Agent",
        description="Test agent for security tests", category="test",
        status=AgentStatus.PUBLISHED, is_verified=True, published_at=datetime.now(UTC),
    )
    db_session.add(agent)
    await db_session.flush()

    version = AgentVersion(
        agent_id=agent.id, version="1.0.0",
        manifest={"runtime": {"image": "agenthub/test-agent"}, "resources": {"cpu": 1, "memory_mb": 512}},
        status=VersionStatus.VERIFIED,
    )
    db_session.add(version)
    await db_session.flush()

    plan = AgentPricingPlan(
        agent_version_id=version.id, name="Standard", pricing_model=PricingModel.PER_HOUR,
        price_minor=200, currency="USD", duration_minutes=30,
    )
    db_session.add(plan)
    await db_session.commit()

    return {
        "cust_a_token": create_access_token(str(cust_a_user.id), "customer"),
        "cust_b_token": create_access_token(str(cust_b_user.id), "customer"),
        "agent_slug": "test-agent",
        "plan_id": str(plan.id),
        "cust_a_id": cust_a.id,
        "cust_b_id": cust_b.id,
    }
