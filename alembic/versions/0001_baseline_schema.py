"""baseline schema — everything in 001_schema.sql

Revision ID: 0001
Revises:
Create Date: 2026-06-21

This represents the database exactly as it already existed before
migrations were introduced. If you're reading this on a FRESH database
that's never been set up, running `alembic upgrade head` creates
everything from scratch. If you're on Michel's existing dev database
(which already has all these tables from when 001_schema.sql was run
by hand), do NOT run upgrade for this one — see the migrations README
for the one-time `alembic stamp` step instead.
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).parent / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "0001_baseline_schema.sql").read_text())


def downgrade() -> None:
    op.execute("drop schema public cascade; create schema public;")
