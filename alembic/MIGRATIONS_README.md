# Database Migrations (Alembic)

Schema changes now go through versioned migration files instead of
pasting SQL into Supabase Studio by hand. This is the real, professional
way to manage a database — every change is recorded, repeatable, and
can be rolled back.

## One-time setup if you already have a database (your current situation)

You already ran `001_schema.sql` and `002_seed.sql` by hand. The first
three migration files (`0001`, `0002`, `0003`) are just those same SQL
files, now wrapped as migrations — so Alembic and your real database
agree on history from this point forward.

**Do NOT run `alembic upgrade head` for these first three.** Your
database already has everything in them — running them would try to
create tables/insert rows that already exist and fail.

Instead, run this **once**:

```bash
alembic stamp head
```

This tells Alembic "the database is already at this version" without
actually running any SQL. Check first whether you ever added the
`otp_codes` table manually (per the earlier README instructions) — if
you skipped that step, add it now via Studio's SQL Editor before
stamping:

```sql
create table otp_codes (
  id           uuid primary key default gen_random_uuid(),
  phone_number text not null,
  code_hash    text not null,
  expires_at   timestamptz not null,
  attempts     int not null default 0,
  created_at   timestamptz not null default now()
);
create index idx_otp_phone on otp_codes(phone_number);
alter table otp_codes enable row level security;
```

## One-time setup on a brand new, empty database (e.g. a future staging/production server)

```bash
alembic upgrade head
```
This runs all three migrations in order and gives you a fully working
database from nothing — schema, otp_codes, and seed reference data
all at once.

## From now on (this is the part that actually matters going forward)

Whenever a table needs to change, you'll get a new migration file
(`0004_something.py`, etc.) instead of a raw SQL snippet to paste
manually. Just run:

```bash
alembic upgrade head
```

That's it — one command, every time, on any database (local, staging,
production). No more copy-pasting SQL into Studio.

To check what migration version your database is currently at:
```bash
alembic current
```
