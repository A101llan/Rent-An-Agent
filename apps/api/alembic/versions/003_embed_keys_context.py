"""Add embed keys and session context metadata

Revision ID: 003
Revises: 002
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rental_sessions",
        sa.Column("context_metadata", postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        "embed_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rental_sessions.id"), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("label", sa.String(255), nullable=False, server_default="Embed widget"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_embed_keys_session_id", "embed_keys", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_embed_keys_session_id", table_name="embed_keys")
    op.drop_table("embed_keys")
    op.drop_column("rental_sessions", "context_metadata")
