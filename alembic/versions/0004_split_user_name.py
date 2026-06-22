"""split full_name into first_name and last_name

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.Text(), nullable=True))
    op.drop_column("users", "full_name")


def downgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.Text(), nullable=True))
    op.drop_column("users", "first_name")
    op.drop_column("users", "last_name")
