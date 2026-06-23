"""add booking acceptance workflow (pending_driver_acceptance, rejected)

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-23

Adds two new possible values to bookings.status: a new INITIAL state
(pending_driver_acceptance, replacing pending_payment as the starting
point) and a terminal one (rejected, for when the driver declines a
request). Uses a DO block to find the existing check constraint by
its actual definition rather than guessing its auto-generated name,
since that name was never set explicitly when the table was created.
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            existing_constraint text;
        BEGIN
            SELECT con.conname INTO existing_constraint
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            WHERE rel.relname = 'bookings'
              AND con.contype = 'c'
              AND pg_get_constraintdef(con.oid) LIKE '%status%';

            IF existing_constraint IS NOT NULL THEN
                EXECUTE 'ALTER TABLE bookings DROP CONSTRAINT ' || existing_constraint;
            END IF;
        END $$;

        ALTER TABLE bookings ADD CONSTRAINT bookings_status_check
            CHECK (status IN (
                'pending_driver_acceptance', 'pending_payment', 'paid',
                'cancelled', 'completed', 'no_show', 'rejected'
            ));

        ALTER TABLE bookings ALTER COLUMN status SET DEFAULT 'pending_driver_acceptance';
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE bookings SET status = 'cancelled' WHERE status IN ('pending_driver_acceptance', 'rejected');

        DO $$
        DECLARE
            existing_constraint text;
        BEGIN
            SELECT con.conname INTO existing_constraint
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            WHERE rel.relname = 'bookings'
              AND con.contype = 'c'
              AND pg_get_constraintdef(con.oid) LIKE '%status%';

            IF existing_constraint IS NOT NULL THEN
                EXECUTE 'ALTER TABLE bookings DROP CONSTRAINT ' || existing_constraint;
            END IF;
        END $$;

        ALTER TABLE bookings ADD CONSTRAINT bookings_status_check
            CHECK (status IN ('pending_payment', 'paid', 'cancelled', 'completed', 'no_show'));

        ALTER TABLE bookings ALTER COLUMN status SET DEFAULT 'pending_payment';
    """)
