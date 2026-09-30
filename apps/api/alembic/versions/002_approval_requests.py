"""Add approval_requests table

Revision ID: 002
Revises: 001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    approval_status = postgresql.ENUM("pending", "approved", "denied", "expired", name="approval_status", create_type=False)
    approval_scope = postgresql.ENUM("once", "session", name="approval_scope", create_type=False)
    approval_status.create(op.get_bind(), checkfirst=True)
    approval_scope.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "approval_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rental_sessions.id")),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_executions.id")),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB()),
        sa.Column("status", approval_status, server_default="pending"),
        sa.Column("scope", approval_scope, nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_approval_requests_session", "approval_requests", ["session_id"])
    op.create_index("idx_approval_requests_status", "approval_requests", ["status"])


def downgrade() -> None:
    op.drop_table("approval_requests")
    op.execute("DROP TYPE IF EXISTS approval_scope")
    op.execute("DROP TYPE IF EXISTS approval_status")
