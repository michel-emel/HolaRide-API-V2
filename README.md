# HolaRide Backend (FastAPI)

## What's new: this backend is now hardened for real use

On top of every feature in the spec, this now includes:
- **Real database migrations** (Alembic) instead of pasting SQL into Studio
- **Phone number validation** (real Cameroon format, not just "any text")
- **Rate limiting** on OTP endpoints (stops SMS-bill abuse and brute-forcing)
- **Consistent error responses** + no leaked stack traces
- **Real logging** instead of print() statements
- **Environment safety net** — OTP dev mode can't accidentally stay on in production
- **Pinned dependency versions** — no surprise breaking updates
- **A Dockerfile** for consistent, repeatable deployment
- **A health check that actually checks the database**, not just "is the process alive"

What's still NOT done — these need real accounts/infrastructure, not code:
a real Mobile Money aggregator contract, a real SMS provider, an actual
server + domain + SSL certificate to deploy to, and a backup strategy
for production data. See the bottom of this file for the full list.

## 1. Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy the example env file and fill it in:
```bash
cp .env.example .env
```
- `DATABASE_URL` — use the connection string `supabase start` printed you
- `JWT_SECRET` — generate one with: `python3 -c "import secrets; print(secrets.token_hex(32))"`
- Leave `ENVIRONMENT=development` for now

## 2. IMPORTANT — one-time migration setup

Schema changes now go through Alembic instead of manual SQL. Since
your database already has everything from `001_schema.sql` and
`002_seed.sql` run by hand, you need to tell Alembic "you're already
caught up" rather than re-running anything.

**Read `alembic/MIGRATIONS_README.md` and follow it before starting
the server.** The short version, if you already added the `otp_codes`
table before: just run
```bash
alembic stamp head
```
If you're not sure whether you added `otp_codes`, the migrations
README has the exact SQL to check/add it first.

## 3. Run the server

```bash
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000/docs** — FastAPI gives you an interactive
tester for every endpoint automatically.

## 4. How roles actually work now

There's no more "sign up as a driver" vs "sign up as a passenger" —
**everyone signs up the same way**, and can do both:

- **Booking a ride** needs nothing special — any logged-in user can do it.
- **Driving** unlocks the moment someone registers a vehicle
  (`POST /drivers/me/vehicle`) **and** admin approves it. The same
  phone number/account can book a ride one day and drive the next.
- **Admin** is the one role still fixed — nobody can self-assign it.
  To make someone an admin, run this directly in Supabase Studio's
  SQL Editor after they've signed up once normally:
  ```sql
  update users set role = 'admin' where phone_number = '+237600000000';
  ```

## 5. Try the full flow

1. **Become an admin** for setup purposes: sign up normally via
   `/auth/otp/request` + `/auth/otp/verify`, then run the SQL above
   to promote that account to admin, then verify OTP again to get a
   fresh token with the admin role in it.
2. **POST /admin/cities**, **/admin/locations**, **/admin/vehicle-categories**,
   **/admin/route-pricing**, **/admin/cancellation-policy-tiers** — skip
   any of these already covered by `002_seed.sql`
3. Sign up a **second, regular account** — this is your driver-to-be
4. **POST /drivers/me/vehicle** — register a car (anyone can call this)
5. Switch to your admin token: **GET /admin/vehicles/pending**, then
   **PATCH /admin/vehicles/{id}** to approve it + assign a category
6. Back to that same regular account's token — it can now create trips:
   **POST /trips**
7. Sign up a **third account** (or reuse the driver's own account —
   nothing stops a driver from also booking a ride!) and
   **POST /trips/{trip_id}/bookings**
8. **POST /bookings/{booking_id}/initiate-payment** — mock provider
   auto-approves, booking becomes `paid`
9. Back to the driver's token: **PATCH /trips/{trip_id}/complete** —
   triggers the payout
10. Try cancelling instead: **PATCH /bookings/{id}/cancel** as the
    rider, or **PATCH /trips/{id}/cancel** as the driver

## 6. What's built

- **Auth**: OTP request/verify/refresh, JWT tokens — single signup
  flow for everyone, admin promoted manually
- **Users**: GET /me
- **Drivers**: register vehicle (open to anyone), list own vehicles —
  driving abilities unlock via an approved vehicle, not a fixed role
- **Admin**: cities, locations, vehicle categories, vehicle approval,
  route pricing, cancellation policy tiers
- **Trips**: create (auto price lookup, requires an approved vehicle),
  search, detail, cancel, mark completed (triggers payout)
- **Bookings**: create (full or 80%-now/20%-later, open to anyone),
  cancel (time-tiered fee), mark no-show (requires an approved vehicle),
  rebook after a driver-cancel
- **Payments**: mock Mobile Money charge, pay remaining 20% balance
- **Payouts**: instant mock payout to driver when a trip is completed
- **Notifications**: logged to the `notifications` table + printed to
  your terminal

## 8. Chat, Live Location & SOS, and Ratings (also now built)

- **Chat**: `GET/POST /trips/{trip_id}/chat/messages` — only the driver
  and any passenger with a `paid` (or `completed`) booking on that trip
  can read or send. This enforces "chat unlocked only after payment"
  automatically, since `get_participant_role()` checks booking status.
- **Live location**: `POST /trips/{trip_id}/location` (anyone on the
  trip pushes their position), `GET /trips/{trip_id}/location/driver`
  (anyone on the trip can see where the driver is)
- **Check-in**: `POST /trips/{trip_id}/checkin` — passenger confirms
  arrival, driver gets notified
- **SOS**: `POST /trips/{trip_id}/sos` — logs an alert and notifies
  everyone else on the trip. There's no real emergency-contact SMS or
  admin dashboard alert yet — see "what's not built" below
- **Ratings**: `POST /trips/{trip_id}/reviews` (stars 1-5 + comment +
  optional emoji, only after the trip is `completed`, one review per
  person per trip), `GET /users/{user_id}/reviews` (average + list)

## 9. What's NOT built yet

**Code that still needs writing:**
- **Real-time delivery for chat/location** — right now the app would
  have to poll these endpoints repeatedly. A real-time channel
  (WebSockets) would make this feel instant instead
- **A real SOS alert pipeline** — right now it logs and notifies trip
  participants; no actual emergency-contact SMS or admin dashboard exists
- **Reports/disputes admin workflow** — the `reports` table exists but
  there's no API for filing or resolving one yet
- **Reminder notifications** (24h/12h/6h/1h/30min/15min before
  departure) — needs a scheduled background job, not built yet
- **Automated tests** — nothing currently verifies these endpoints
  keep working as you keep changing things

**Things that need YOUR decisions/accounts, not code:**
- A real Mobile Money aggregator contract (PawaPay is now wired up
  for sandbox — see section 11 below for production credentials)
- A real SMS provider account (currently logs the OTP instead of
  texting it)
- An actual server + domain + SSL certificate to deploy to
- A backup strategy for real production data
- Error monitoring (e.g. Sentry) so you find out about crashes before
  a user complains

## 10. Running with Docker (optional, for later deployment)

```bash
docker compose up --build
```
See the comments inside `docker-compose.yml` for the one thing to
watch out for (how `DATABASE_URL`'s host needs to change once the
backend itself is inside a container).

## 11. Real PawaPay integration (replaces the old mock)

Payments and payouts now call PawaPay's real sandbox API instead of
auto-approving instantly. Two things changed because of this:

**Setup:**
1. Get a sandbox token from your PawaPay dashboard → Developers → API tokens
2. Put it in `.env` as `PAWAPAY_API_TOKEN` — never anywhere else
3. `pip install -r requirements.txt` (adds the `requests` library)

**The flow is now genuinely asynchronous** — a real Mobile Money charge
requires the customer to approve it on their phone, so there's no
instant "success" anymore:

- `POST /bookings/{id}/initiate-payment` → returns `payment_status: "pending"`
  immediately (this is normal, not stuck)
- Two ways to find out the real outcome:
  1. **Polling** (works without any extra setup): the app calls
     `GET /bookings/{id}/payment-status` every few seconds until the
     status changes
  2. **Webhook** (instant, but needs a public URL): set
     `POST /payments/webhook/pawapay` as your callback URL in the
     PawaPay sandbox dashboard. For local testing, your laptop doesn't
     have a public URL by default — use a tool like **ngrok**
     (`ngrok http 8000`) to get one temporarily, paste that into the
     PawaPay dashboard, and PawaPay can then reach your local server.

Driver payouts work the same way: `PATCH /trips/{id}/complete` starts
the payout, and `GET /drivers/me/payouts/{id}/status` polls for the
real outcome (or the same webhook handles it instantly).

## 12. Real SMS integration — Termii (active) or Twilio (fallback)

`app/services/sms.py` stays in dev mode (logs the code) until you set
`OTP_DEV_MODE=false`. Once you do, `SMS_PROVIDER` decides which real
provider actually sends it — defaults to **Termii**.

**Termii setup** (the default):
```
TERMII_API_KEY=...
TERMII_SENDER_ID=...
TERMII_CHANNEL=dnd
SMS_PROVIDER=termii
```
Get the API key and sender ID from your Termii dashboard. **Important:**
Termii's own docs say the `dnd` channel is what OTPs should use —
the `generic` channel risks delivery failures or your sender ID
getting blocked for OTP traffic. `dnd` needs to be activated on your
account by Termii's support team first; if you haven't done that yet,
set `TERMII_CHANNEL=generic` as a temporary stopgap, but switch back
to `dnd` as soon as it's enabled.

**Twilio setup** (fallback option, set `SMS_PROVIDER=twilio` to use it):
```
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=...
```
Trial accounts can only deliver to phone numbers you've manually
verified first at console.twilio.com → Phone Numbers → Verified
Caller IDs — if a test OTP never arrives, check this first.

```bash
docker compose up --build
```
See the comments inside `docker-compose.yml` for the one thing to
watch out for (how `DATABASE_URL`'s host needs to change once the
backend itself is inside a container).
