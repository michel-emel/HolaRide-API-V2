"""add reference_id to notifications

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # reference_id is a plain nullable UUID with no FK constraint —
    # intentionally. It can point at a trip, a booking, or nothing at
    # all depending on the notification type, and adding per-type FK
    # constraints would make notify_user() far more complex for no
    # real referential-integrity benefit (notifications are read-only
    # history; the referenced entity being deleted doesn't matter).
    op.add_column(
        "notifications",
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column(
            "read_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.create_index("idx_notifications_user_read", "notifications", ["user_id", "read_at"])


def downgrade() -> None:
    op.drop_index("idx_notifications_user_read", table_name="notifications")
    op.drop_column("notifications", "read_at")
    op.drop_column("notifications", "reference_id")
