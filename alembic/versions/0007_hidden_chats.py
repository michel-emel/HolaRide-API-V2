"""add hidden_chats table

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hidden_chats",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trips.id"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "trip_id", name="uq_hidden_chats_user_trip"),
    )
    op.create_index("idx_hidden_chats_user", "hidden_chats", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_hidden_chats_user", table_name="hidden_chats")
    op.drop_table("hidden_chats")