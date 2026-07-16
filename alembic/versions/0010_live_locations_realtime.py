"""live_locations: heading, upsert key, RLS asymmetry, realtime

Revision ID: 0009_live_locations_realtime
Revises: <METS ICI TON HEAD ACTUEL — vérifie avec `alembic heads`>
"""
from alembic import op

revision = "0010"
down_revision = "0009"   
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        -- Orientation du véhicule (degrés), pour faire pivoter le marqueur
        alter table live_locations
            add column if not exists heading double precision;

        -- Une seule ligne par (trajet, utilisateur) → upsert au lieu d'append
        alter table live_locations
            add constraint uq_live_locations_trip_user unique (trip_id, user_id);

        -- ── Sécurité : asymétrie imposée par la base ──────────────
        alter table live_locations enable row level security;

        -- Le CHAUFFEUR du trajet voit toutes les positions du trajet
        -- (les siennes + celles de ses passagers)
        create policy driver_sees_trip_positions on live_locations
        for select using (
            exists (
                select 1 from trips t
                where t.id = live_locations.trip_id
                  and t.driver_id = auth.uid()
            )
        );

        -- Un PASSAGER payé du trajet ne voit QUE la ligne du chauffeur
        create policy passenger_sees_driver_only on live_locations
        for select using (
            user_id = (select driver_id from trips where id = live_locations.trip_id)
            and exists (
                select 1 from bookings b
                where b.trip_id = live_locations.trip_id
                  and b.passenger_id = auth.uid()
                  and b.status = 'paid'
            )
        );

        -- ── Activation Realtime sur cette table ───────────────────
        alter publication supabase_realtime add table live_locations;
    """)


def downgrade():
    op.execute("""
        alter publication supabase_realtime drop table live_locations;
        drop policy if exists passenger_sees_driver_only on live_locations;
        drop policy if exists driver_sees_trip_positions on live_locations;
        alter table live_locations disable row level security;
        alter table live_locations drop constraint if exists uq_live_locations_trip_user;
        alter table live_locations drop column if exists heading;
    """)