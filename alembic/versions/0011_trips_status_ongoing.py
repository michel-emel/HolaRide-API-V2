"""allow 'ongoing' in trips.status check constraint

Revision ID: 0011_trips_status_ongoing
Revises: 0010_live_locations_realtime
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

# ⚠️ Adapte ces deux listes à ce que le SELECT t'a montré
_OLD = "('draft','published','completed','cancelled')"
_NEW = "('draft','published','ongoing','completed','cancelled')"


def upgrade():
    op.execute(f"""
        alter table trips drop constraint if exists trips_status_check;
        alter table trips add constraint trips_status_check
            check (status in {_NEW});
    """)


def downgrade():
    op.execute(f"""
        alter table trips drop constraint if exists trips_status_check;
        alter table trips add constraint trips_status_check
            check (status in {_OLD});
    """)