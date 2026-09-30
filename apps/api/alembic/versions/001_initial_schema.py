"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-08-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"pgcrypto\"")

    user_role = postgresql.ENUM("customer", "developer", "admin", name="user_role", create_type=False)
    developer_status = postgresql.ENUM("pending", "approved", "suspended", "rejected", name="developer_status", create_type=False)
    agent_status = postgresql.ENUM("draft", "pending_review", "published", "suspended", "archived", name="agent_status", create_type=False)
    version_status = postgresql.ENUM("draft", "pending_verification", "verified", "disabled", name="version_status", create_type=False)
    verification_status = postgresql.ENUM("pending", "scanning", "testing", "passed", "failed", name="verification_status", create_type=False)
    pricing_model = postgresql.ENUM("per_minute", "per_hour", "per_task", "per_request", "subscription", name="pricing_model", create_type=False)
    rental_status = postgresql.ENUM("pending", "active", "paused", "expired", "cancelled", "terminated", "failed", name="rental_status", create_type=False)
    session_status = postgresql.ENUM("pending", "active", "expired", "terminated", name="session_status", create_type=False)
    runtime_status = postgresql.ENUM("provisioning", "starting", "running", "stopping", "terminated", "failed", name="runtime_status", create_type=False)
    network_policy = postgresql.ENUM("none", "internet_read", "internet_full", "allowlist", name="network_policy", create_type=False)
    execution_status = postgresql.ENUM("pending", "running", "completed", "failed", "waiting_for_approval", "cancelled", name="execution_status", create_type=False)
    transaction_type = postgresql.ENUM("charge", "refund", "extension", "subscription", name="transaction_type", create_type=False)
    transaction_status = postgresql.ENUM("pending", "completed", "failed", "refunded", name="transaction_status", create_type=False)

    for enum in [user_role, developer_status, agent_status, version_status, verification_status,
                 pricing_model, rental_status, session_status, runtime_status, network_policy,
                 execution_status, transaction_type, transaction_status]:
        enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_users_email", "users", ["email"])

    op.create_table(
        "developer_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("company_name", sa.String(255)),
        sa.Column("bio", sa.Text()),
        sa.Column("status", developer_status, server_default="pending"),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "customer_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), unique=True),
        sa.Column("display_name", sa.String(255)),
        sa.Column("organization", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("prefix", sa.String(8), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("developer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("developer_profiles.id")),
        sa.Column("slug", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("icon_url", sa.String(500)),
        sa.Column("status", agent_status, server_default="draft"),
        sa.Column("is_featured", sa.Boolean(), server_default="false"),
        sa.Column("is_verified", sa.Boolean(), server_default="false"),
        sa.Column("avg_rating", sa.Numeric(3, 2), server_default="0"),
        sa.Column("review_count", sa.Integer(), server_default="0"),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "agent_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id")),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("runtime_requirements", postgresql.JSONB()),
        sa.Column("configuration", postgresql.JSONB()),
        sa.Column("status", version_status, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "version"),
    )

    op.create_table(
        "agent_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_versions.id"), unique=True),
        sa.Column("image_registry", sa.String(500), nullable=False),
        sa.Column("image_name", sa.String(255), nullable=False),
        sa.Column("image_digest", sa.String(128), nullable=False, unique=True),
        sa.Column("manifest_url", sa.String(500)),
        sa.Column("verification_status", verification_status, server_default="pending"),
        sa.Column("scan_results", postgresql.JSONB()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "agent_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_versions.id")),
        sa.Column("capability", sa.String(100), nullable=False),
        sa.UniqueConstraint("agent_version_id", "capability"),
    )

    op.create_table(
        "agent_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_versions.id")),
        sa.Column("permission", sa.String(100), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), server_default="false"),
    )

    op.create_table(
        "agent_pricing_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_versions.id")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("pricing_model", pricing_model, nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("duration_minutes", sa.Integer()),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
    )

    op.create_table(
        "rentals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer_profiles.id")),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id")),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_versions.id")),
        sa.Column("pricing_plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_pricing_plans.id")),
        sa.Column("status", rental_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("total_cost_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("idempotency_key", sa.String(255), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "rental_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rental_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rentals.id")),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("status", session_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True)),
        sa.Column("runtime_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.create_table(
        "runtime_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rental_sessions.id")),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_versions.id")),
        sa.Column("runtime_provider", sa.String(50), server_default="docker"),
        sa.Column("runtime_identifier", sa.String(255)),
        sa.Column("status", runtime_status, nullable=False),
        sa.Column("cpu_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("memory_limit_mb", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column("network_policy", network_policy, server_default="none"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("terminated_at", sa.DateTime(timezone=True)),
    )

    op.create_foreign_key(
        "fk_rental_sessions_runtime_instance",
        "rental_sessions", "runtime_instances",
        ["runtime_instance_id"], ["id"],
    )

    op.create_table(
        "agent_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id")),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer_profiles.id")),
        sa.Column("rental_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rentals.id")),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("title", sa.String(255)),
        sa.Column("body", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "customer_id", "rental_id"),
    )

    op.create_table(
        "agent_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rental_sessions.id")),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_versions.id")),
        sa.Column("status", execution_status, nullable=False),
        sa.Column("input_metadata", postgresql.JSONB()),
        sa.Column("output_metadata", postgresql.JSONB()),
        sa.Column("usage_summary", postgresql.JSONB()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rental_sessions.id")),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_executions.id")),
        sa.Column("metric_type", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer_profiles.id")),
        sa.Column("rental_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rentals.id")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rental_sessions.id")),
        sa.Column("type", transaction_type, nullable=False),
        sa.Column("gross_amount_minor", sa.Integer(), nullable=False),
        sa.Column("developer_amount_minor", sa.Integer(), nullable=False),
        sa.Column("platform_fee_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("status", transaction_status, nullable=False),
        sa.Column("idempotency_key", sa.String(255), unique=True),
        sa.Column("external_ref", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "platform_fees",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transactions.id"), unique=True),
        sa.Column("fee_rate_bps", sa.Integer(), nullable=False),
        sa.Column("platform_amount_minor", sa.Integer(), nullable=False),
        sa.Column("developer_amount_minor", sa.Integer(), nullable=False),
    )

    op.create_table(
        "agent_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rental_sessions.id")),
        sa.Column("credential_type", sa.String(50), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("request_id", sa.String(64)),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "security_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("request_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customer_profiles.id")),
        sa.Column("integration_type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("config", postgresql.JSONB()),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in [
        "integrations", "notifications", "security_events", "audit_logs",
        "agent_credentials", "platform_fees", "transactions", "usage_records",
        "agent_executions", "agent_reviews", "runtime_instances", "rental_sessions",
        "rentals", "agent_pricing_plans", "agent_permissions", "agent_capabilities",
        "agent_artifacts", "agent_versions", "agents", "api_keys", "refresh_tokens",
        "customer_profiles", "developer_profiles", "users",
    ]:
        op.drop_table(table)

    for enum in [
        "transaction_status", "transaction_type", "execution_status", "network_policy",
        "runtime_status", "session_status", "rental_status", "pricing_model",
        "verification_status", "version_status", "agent_status", "developer_status", "user_role",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum}")
