"""add first_name and last_name to otp_codes

Revision ID: 0009
Revises: 0008
Create Date: 2025-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('otp_codes', sa.Column('first_name', sa.String(), nullable=True))
    op.add_column('otp_codes', sa.Column('last_name',  sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('otp_codes', 'last_name')
    op.drop_column('otp_codes', 'first_name')
