"""add otp_codes table

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-21
"""
from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).parent / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "0002_add_otp_codes.sql").read_text())


def downgrade() -> None:
    op.execute("drop table if exists otp_codes;")
