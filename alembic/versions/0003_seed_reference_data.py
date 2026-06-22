"""seed reference data — cities, locations, vehicle categories, route pricing, cancellation tiers

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-21

This is a DATA migration, not a schema change — it's what used to be
002_seed.sql. Only meant to run once on a brand new, empty database.
If you run this against Michel's existing dev database it will fail
on duplicate cities/etc — that's expected, see the migrations README.
"""
from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).parent / "sql"


def upgrade() -> None:
    op.execute((SQL_DIR / "0003_seed_reference_data.sql").read_text())


def downgrade() -> None:
    op.execute("""
        delete from route_pricing;
        delete from routes;
        delete from vehicle_categories;
        delete from locations;
        delete from cities;
        delete from cancellation_policy_tiers;
    """)
