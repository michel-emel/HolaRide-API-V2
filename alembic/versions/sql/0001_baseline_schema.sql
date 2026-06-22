-- ============================================================
-- HolaRide MVP — Database Schema
-- PostgreSQL / Supabase-ready
--
-- HOW TO USE THIS FILE:
-- 1. Run this on a local Postgres database first (see SETUP notes
--    at the bottom of the chat message, not in this file).
-- 2. Once you're happy with it locally, run the EXACT same file
--    on your Supabase project's SQL Editor. Supabase IS Postgres,
--    so nothing needs to change between local and Supabase.
-- 3. Run 002_seed.sql AFTER this file to get example data
--    (cities, routes, prices, cancellation tiers) to test with.
-- ============================================================

-- Supabase enables this by default. If running on plain local
-- Postgres, this line makes gen_random_uuid() available.
create extension if not exists "pgcrypto";

-- ============================================================
-- 1. USERS
-- One account = one role. A person who is both a driver and a
-- passenger would need two separate accounts in this MVP design.
-- ============================================================
create table users (
  id              uuid primary key default gen_random_uuid(),
  phone_number    text not null unique,
  full_name       text,
  role            text not null check (role in ('driver', 'passenger', 'admin')),
  phone_verified  boolean not null default false,
  is_active       boolean not null default true,
  created_at      timestamptz not null default now()
);

create index idx_users_role on users(role);

-- Extra info that only exists for drivers, kept separate so the
-- users table stays clean for passengers/admins.
create table driver_profiles (
  user_id            uuid primary key references users(id) on delete cascade,
  reliability_score  numeric not null default 100 check (reliability_score >= 0),
  identity_verified  boolean not null default false,
  created_at         timestamptz not null default now()
);

-- ============================================================
-- 2. GEOGRAPHY
-- ============================================================
create table cities (
  id    uuid primary key default gen_random_uuid(),
  name  text not null unique
);

create table locations (
  id       uuid primary key default gen_random_uuid(),
  city_id  uuid not null references cities(id) on delete cascade,
  name     text not null,
  unique (city_id, name)
);

create index idx_locations_city on locations(city_id);

-- speeds up "start typing and suggestions pop up" search
-- (extension must be created BEFORE it's used in the index below)
create extension if not exists pg_trgm;
create index idx_locations_name_trgm on locations using gin (name gin_trgm_ops);

-- ============================================================
-- 3. VEHICLES & CATEGORIES
-- Category is assigned by admin AT REGISTRATION and does not
-- change at trip-creation time.
-- ============================================================
create table vehicle_categories (
  id           uuid primary key default gen_random_uuid(),
  name         text not null unique,      -- e.g. 'Comfort', 'Premium'
  description  text
);

create table vehicles (
  id                   uuid primary key default gen_random_uuid(),
  driver_id            uuid not null references users(id) on delete cascade,
  brand                text not null,
  model                text not null,
  year                 int,
  color                text,
  plate_number         text not null unique,
  total_seats          int not null check (total_seats > 0),
  vehicle_category_id  uuid references vehicle_categories(id),  -- null until admin approves
  verification_status  text not null default 'pending'
                         check (verification_status in ('pending', 'approved', 'rejected')),
  created_at           timestamptz not null default now()
);

create index idx_vehicles_driver on vehicles(driver_id);

-- ============================================================
-- 4. ROUTES & PRICING (admin-controlled)
-- ============================================================
create table routes (
  id                    uuid primary key default gen_random_uuid(),
  origin_city_id        uuid not null references cities(id),
  destination_city_id   uuid not null references cities(id),
  unique (origin_city_id, destination_city_id),
  check (origin_city_id <> destination_city_id)
);

create table route_pricing (
  id                    uuid primary key default gen_random_uuid(),
  route_id              uuid not null references routes(id) on delete cascade,
  vehicle_category_id   uuid not null references vehicle_categories(id),
  price_per_seat        numeric not null check (price_per_seat > 0),
  unique (route_id, vehicle_category_id)
);

-- ============================================================
-- 5. CANCELLATION POLICY (admin-configurable, no redeploy needed)
-- No-show is intentionally NOT in this table — it's a fixed
-- 100% forfeiture handled directly in application logic.
-- ============================================================
create table cancellation_policy_tiers (
  id                uuid primary key default gen_random_uuid(),
  min_hours_before  int not null,
  max_hours_before  int,   -- null means "no upper bound" (the >24h tier)
  fee_percentage    numeric not null check (fee_percentage between 0 and 100)
);

-- ============================================================
-- 6. TRIPS
-- price_per_seat is SNAPSHOTTED here at creation time from
-- route_pricing, so a later admin price change never retroactively
-- changes a trip that's already published.
-- ============================================================
create table trips (
  id                       uuid primary key default gen_random_uuid(),
  driver_id                uuid not null references users(id),
  vehicle_id               uuid not null references vehicles(id),
  route_id                 uuid not null references routes(id),
  departure_location_id    uuid not null references locations(id),
  destination_location_id  uuid not null references locations(id),
  departure_date           date not null,
  departure_time           time not null,
  available_seats          int not null check (available_seats >= 0),
  price_per_seat           numeric not null check (price_per_seat > 0),
  status                   text not null default 'draft'
                            check (status in
                              ('draft', 'published', 'boarding', 'full',
                               'in_progress', 'completed', 'cancelled')),
  created_at               timestamptz not null default now()
);

create index idx_trips_route_date on trips(route_id, departure_date);
create index idx_trips_driver on trips(driver_id);
create index idx_trips_status on trips(status);

-- ============================================================
-- 7. BOOKINGS
-- seats_booked supports passengers booking more than one seat.
-- payment_type + outstanding_balance support the 80%-now /
-- 20%-later option.
-- ============================================================
create table bookings (
  id                   uuid primary key default gen_random_uuid(),
  trip_id              uuid not null references trips(id),
  passenger_id         uuid not null references users(id),
  seats_booked         int not null check (seats_booked > 0),
  price_total          numeric not null,        -- price_per_seat * seats_booked at booking time
  payment_type         text not null default 'full'
                        check (payment_type in ('full', 'partial_80')),
  amount_paid          numeric not null default 0,
  outstanding_balance  numeric not null default 0,
  status               text not null default 'pending_payment'
                        check (status in
                          ('pending_payment', 'paid', 'cancelled', 'completed', 'no_show')),
  created_at           timestamptz not null default now()
);

create index idx_bookings_trip on bookings(trip_id);
create index idx_bookings_passenger on bookings(passenger_id);
create index idx_bookings_outstanding on bookings(passenger_id, outstanding_balance)
  where outstanding_balance > 0;

-- ============================================================
-- 8. PAYMENTS (passenger -> platform collections)
-- A booking can have more than one row here: e.g. one 'initial_80'
-- row when booking, and one 'balance_settlement' row later.
-- ============================================================
create table payments (
  id                      uuid primary key default gen_random_uuid(),
  booking_id              uuid not null references bookings(id),
  provider                text not null,             -- e.g. 'mtn_momo', 'orange_money'
  provider_transaction_id text,
  amount                  numeric not null check (amount > 0),
  purpose                 text not null default 'full'
                           check (purpose in ('full', 'initial_80', 'balance_settlement')),
  status                  text not null default 'pending'
                           check (status in ('pending', 'success', 'failed')),
  created_at              timestamptz not null default now()
);

create index idx_payments_booking on payments(booking_id);

-- ============================================================
-- 9. CANCELLATIONS
-- ============================================================
create table cancellations (
  id            uuid primary key default gen_random_uuid(),
  booking_id    uuid not null references bookings(id),
  cancelled_by  text not null check (cancelled_by in ('driver', 'passenger')),
  reason        text,
  fee_charged   numeric not null default 0,
  refund_amount numeric not null default 0,
  rebooked_to   uuid references bookings(id),   -- filled in if driver-cancel led to a rebooking
  created_at    timestamptz not null default now()
);

create index idx_cancellations_booking on cancellations(booking_id);

-- Audit trail for WHY a driver's reliability_score changed.
-- Keeps driver_profiles.reliability_score as a fast-to-read number
-- while still letting admin see the history behind it.
create table driver_reliability_log (
  id                uuid primary key default gen_random_uuid(),
  driver_id         uuid not null references users(id),
  event_type        text not null check (event_type in ('trip_cancelled', 'no_show_reported', 'positive_trip')),
  points_impact     numeric not null,
  related_trip_id   uuid references trips(id),
  created_at        timestamptz not null default now()
);

-- ============================================================
-- 10. PAYOUTS (platform -> driver disbursements)
-- ============================================================
create table payouts (
  id                uuid primary key default gen_random_uuid(),
  driver_id         uuid not null references users(id),
  trip_id           uuid not null references trips(id),
  provider          text not null,
  provider_payout_id text,
  amount            numeric not null check (amount > 0),
  status            text not null default 'pending'
                     check (status in ('pending', 'success', 'failed', 'retrying')),
  created_at        timestamptz not null default now()
);

create index idx_payouts_driver on payouts(driver_id);
create index idx_payouts_trip on payouts(trip_id);

-- ============================================================
-- 11. CHAT (unlocked only after payment — enforced in app logic)
-- ============================================================
create table trip_chats (
  id          uuid primary key default gen_random_uuid(),
  trip_id     uuid not null unique references trips(id),
  created_at  timestamptz not null default now()
);

create table messages (
  id            uuid primary key default gen_random_uuid(),
  chat_id       uuid not null references trip_chats(id) on delete cascade,
  sender_id     uuid references users(id),   -- null for pure system messages
  content       text,
  message_type  text not null default 'text' check (message_type in ('text', 'system', 'image')),
  created_at    timestamptz not null default now()
);

create index idx_messages_chat on messages(chat_id, created_at);

-- ============================================================
-- 12. LIVE LOCATION & SAFETY
-- ============================================================
create table live_locations (
  id          uuid primary key default gen_random_uuid(),
  trip_id     uuid not null references trips(id),
  user_id     uuid not null references users(id),
  latitude    numeric not null,
  longitude   numeric not null,
  updated_at  timestamptz not null default now(),
  unique (trip_id, user_id)   -- one current-location row per person per trip
);

create table sos_alerts (
  id                          uuid primary key default gen_random_uuid(),
  trip_id                     uuid not null references trips(id),
  triggered_by                uuid not null references users(id),
  latitude                    numeric,
  longitude                   numeric,
  emergency_contact_notified  boolean not null default false,
  status                      text not null default 'open' check (status in ('open', 'resolved')),
  created_at                  timestamptz not null default now()
);

-- ============================================================
-- 13. NOTIFICATIONS
-- ============================================================
create table notifications (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references users(id),
  type        text not null,         -- e.g. 'booking_confirmed', 'payout_sent'
  title       text,
  body        text,
  channel     text check (channel in ('push', 'sms', 'whatsapp')),
  status      text not null default 'pending' check (status in ('pending', 'sent', 'failed')),
  created_at  timestamptz not null default now()
);

create index idx_notifications_user on notifications(user_id, created_at);

create table device_tokens (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references users(id) on delete cascade,
  token       text not null,
  platform    text check (platform in ('ios', 'android')),
  created_at  timestamptz not null default now()
);

-- ============================================================
-- 14. RATINGS (stars + comment + optional quick-reaction emoji)
-- ============================================================
create table reviews (
  id              uuid primary key default gen_random_uuid(),
  trip_id         uuid not null references trips(id),
  reviewer_id     uuid not null references users(id),
  reviewee_id     uuid not null references users(id),
  reviewer_role   text not null check (reviewer_role in ('passenger', 'driver')),
  stars           int not null check (stars between 1 and 5),
  comment         text,
  emoji_reaction  text,   -- optional quick reaction, separate from the star score
  created_at      timestamptz not null default now()
);

create index idx_reviews_reviewee on reviews(reviewee_id);

-- ============================================================
-- 15. ADMIN: DISPUTES & REPORTS
-- ============================================================
create table reports (
  id                 uuid primary key default gen_random_uuid(),
  reporter_id        uuid not null references users(id),
  reported_user_id   uuid references users(id),
  trip_id            uuid references trips(id),
  category           text,
  description        text,
  status             text not null default 'open' check (status in ('open', 'investigating', 'resolved')),
  admin_notes        text,
  created_at         timestamptz not null default now(),
  resolved_at        timestamptz
);

-- ============================================================
-- 16. ROW LEVEL SECURITY
--
-- Your Flutter app talks to YOUR OWN backend, not directly to
-- Supabase's auto-generated API. Your backend should connect
-- using the `service_role` key, which always bypasses RLS
-- regardless of the policies (or lack of policies) below.
--
-- Enabling RLS here with NO policies attached means: the public
-- REST/GraphQL API (anon/authenticated keys) is fully locked —
-- nobody can read or write anything through it. Your backend's
-- access is completely unaffected.
--
-- In short: this locks a front door you don't plan to use,
-- in case its key ever leaks. Costs nothing, adds a safety net.
-- ============================================================
alter table users enable row level security;
alter table driver_profiles enable row level security;
alter table cities enable row level security;
alter table locations enable row level security;
alter table vehicle_categories enable row level security;
alter table vehicles enable row level security;
alter table routes enable row level security;
alter table route_pricing enable row level security;
alter table cancellation_policy_tiers enable row level security;
alter table trips enable row level security;
alter table bookings enable row level security;
alter table payments enable row level security;
alter table cancellations enable row level security;
alter table driver_reliability_log enable row level security;
alter table payouts enable row level security;
alter table trip_chats enable row level security;
alter table messages enable row level security;
alter table live_locations enable row level security;
alter table sos_alerts enable row level security;
alter table notifications enable row level security;
alter table device_tokens enable row level security;
alter table reviews enable row level security;
alter table reports enable row level security;

-- ============================================================
-- DONE. Run 002_seed.sql next to load example cities, routes,
-- prices and cancellation tiers for local testing.
-- ============================================================
