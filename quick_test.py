"""
Quick end-to-end test script — covers the full backend: signup, admin
setup, driver/vehicle approval, trip creation, booking, multi-seat,
search, admin pricing updates, chat, live location, check-in, SOS,
ratings, and all three cancellation/no-show paths.

USAGE:
    1. Make sure your server is already running (uvicorn app.main:app --reload)
    2. Make sure OTP_DEV_MODE=true in your .env
    3. Run, from the project root, with your venv active:
       python3 quick_test.py

This directly updates your LOCAL database — don't run this against
a real production database. In particular, step "force_mark_paid"
below bypasses real Mobile Money payment ON PURPOSE, only so the
script can test features that require a paid booking (chat, location,
check-in, SOS, ratings) without needing a real phone to approve a
real charge every single run. This shortcut must never exist outside
a test script — the actual app must always go through real payment.
"""
import sys
from datetime import date, timedelta

import psycopg2
import requests

from app.config import settings

BASE_URL = "http://127.0.0.1:8000"

ADMIN_PHONE = "+237600000001"
DRIVER_PHONE = "+237600000002"
PASSENGER_PHONE = "+237600000003"
PASSENGER2_PHONE = "+237600000004"

TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def step(label):
    print(f"\n--- {label} ---")


def fail(message):
    print(f"FAILED: {message}")
    sys.exit(1)


def ok(message):
    print(f"OK: {message}")


def parse_or_fail(resp, context):
    if resp.status_code not in (200, 201):
        fail(f"{context}: got status {resp.status_code}\nResponse body: {resp.text}")
    try:
        return resp.json()
    except ValueError:
        fail(f"{context}: response wasn't valid JSON\nResponse body: {resp.text}")


def signup_or_login(phone, first_name=None, last_name=None):
    resp = requests.post(f"{BASE_URL}/auth/otp/request", json={"phone_number": phone})
    data = parse_or_fail(resp, f"otp/request for {phone}")
    code = data.get("dev_otp_code")
    if not code:
        fail("No dev_otp_code in response — is OTP_DEV_MODE=true in your .env?")

    body = {"phone_number": phone, "code": code}
    if first_name:
        body["first_name"] = first_name
    if last_name:
        body["last_name"] = last_name

    resp = requests.post(f"{BASE_URL}/auth/otp/verify", json=body)
    data = parse_or_fail(resp, f"otp/verify for {phone}")
    return data["access_token"]


def db_conn():
    return psycopg2.connect(settings.database_url)


def promote_to_admin(phone):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("update users set role = 'admin' where phone_number = %s", (phone,))
    conn.commit()
    cur.close()
    conn.close()


def force_mark_paid(booking_id, amount):
    """
    TEST-ONLY SHORTCUT. Real bookings only become 'paid' through a real
    PawaPay charge being confirmed (see app/routers/payments.py). This
    bypasses that entirely so the script can test post-payment features
    (chat, location, check-in, SOS, ratings) without spending real money
    or needing a real phone every run. NEVER do this in the actual app.
    """
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        "update bookings set status = 'paid', amount_paid = %s, outstanding_balance = 0 where id = %s",
        (amount, booking_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def get_user_id(token):
    resp = requests.get(f"{BASE_URL}/me", headers=auth_headers(token))
    return parse_or_fail(resp, "GET /me")["id"]


def create_trip(driver_token, vehicle_id, dep_loc_id, dest_loc_id, seats=3, dep_date=TOMORROW):
    resp = requests.post(
        f"{BASE_URL}/trips",
        headers=auth_headers(driver_token),
        json={
            "vehicle_id": vehicle_id,
            "departure_location_id": dep_loc_id,
            "destination_location_id": dest_loc_id,
            "departure_date": dep_date,
            "departure_time": "08:00:00",
            "available_seats": seats,
        },
    )
    return parse_or_fail(resp, "trip creation")


def book_and_force_pay(passenger_token, trip_id, seats=1):
    resp = requests.post(
        f"{BASE_URL}/trips/{trip_id}/bookings",
        headers=auth_headers(passenger_token),
        json={"seats_booked": seats, "payment_type": "full"},
    )
    booking = parse_or_fail(resp, "booking")
    force_mark_paid(booking["id"], booking["price_total"])
    return booking


def main():
    # ---- 1-9: core happy path (unchanged from before) ----
    step(f"1. Admin signup/login ({ADMIN_PHONE})")
    admin_token = signup_or_login(ADMIN_PHONE, "Admin", "User")
    ok("got admin token (not yet admin role)")

    step("2. Promoting to admin in the database")
    promote_to_admin(ADMIN_PHONE)
    admin_token = signup_or_login(ADMIN_PHONE)
    ok("re-issued token now carries role=admin")

    step("3. Checking seeded reference data exists")
    cities = {c["name"]: c["id"] for c in parse_or_fail(
        requests.get(f"{BASE_URL}/admin/cities", headers=auth_headers(admin_token)), "GET /admin/cities"
    )}
    categories = {c["name"]: c["id"] for c in parse_or_fail(
        requests.get(f"{BASE_URL}/admin/vehicle-categories", headers=auth_headers(admin_token)), "GET /admin/vehicle-categories"
    )}
    locations = {loc["name"]: loc["id"] for loc in parse_or_fail(
        requests.get(f"{BASE_URL}/admin/locations", headers=auth_headers(admin_token)), "GET /admin/locations"
    )}
    if "Deido" not in locations or "Mvan" not in locations:
        fail(f"Expected locations Deido/Mvan not found. Got: {list(locations.keys())}")
    ok(f"cities={list(cities.keys())}, categories={list(categories.keys())}, locations OK")

    step(f"4. Driver signup/login ({DRIVER_PHONE})")
    driver_token = signup_or_login(DRIVER_PHONE, "Test", "Driver")
    ok("got driver token")

    step("5. Registering a vehicle")
    existing = parse_or_fail(
        requests.get(f"{BASE_URL}/drivers/me/vehicles", headers=auth_headers(driver_token)), "list driver vehicles"
    )
    if existing:
        vehicle = existing[0]
        ok(f"reusing existing vehicle id={vehicle['id']}, status={vehicle['verification_status']}")
    else:
        resp = requests.post(
            f"{BASE_URL}/drivers/me/vehicle",
            headers=auth_headers(driver_token),
            json={"brand": "Toyota", "model": "Corolla", "year": 2018, "color": "Blue",
                  "plate_number": f"TEST-{DRIVER_PHONE[-4:]}", "total_seats": 4},
        )
        vehicle = parse_or_fail(resp, "vehicle registration")
        ok(f"registered vehicle id={vehicle['id']}")

    step("6. Admin approving the vehicle")
    parse_or_fail(
        requests.patch(
            f"{BASE_URL}/admin/vehicles/{vehicle['id']}", headers=auth_headers(admin_token),
            json={"verification_status": "approved", "vehicle_category_id": categories["Comfort"]},
        ),
        "vehicle approval",
    )
    ok("vehicle approved")

    step("7. Driver creating the MAIN trip (Deido -> Mvan)")
    trip = create_trip(driver_token, vehicle["id"], locations["Deido"], locations["Mvan"])
    ok(f"trip id={trip['id']}, price_per_seat={trip['price_per_seat']}")

    step(f"8. Passenger signup/login ({PASSENGER_PHONE})")
    passenger_token = signup_or_login(PASSENGER_PHONE, "Test", "Passenger")
    passenger_id = get_user_id(passenger_token)
    ok(f"got passenger token, user id={passenger_id}")

    step("9. Booking 2 seats (multi-seat test)")
    resp = requests.post(
        f"{BASE_URL}/trips/{trip['id']}/bookings",
        headers=auth_headers(passenger_token),
        json={"seats_booked": 2, "payment_type": "full"},
    )
    booking = parse_or_fail(resp, "booking")
    if booking["seats_booked"] != 2:
        fail(f"Expected seats_booked=2, got {booking['seats_booked']}")
    ok(f"booking id={booking['id']}, seats_booked={booking['seats_booked']}, status={booking['status']}")

    # ---- 10: search ----
    step("10. Searching for the trip by city")
    results = parse_or_fail(
        requests.get(f"{BASE_URL}/trips/search", params={"origin_city": "Douala", "destination_city": "Yaoundé"}),
        "GET /trips/search",
    )
    if not any(t["id"] == trip["id"] for t in results):
        fail(f"Main trip not found in search results. Got {len(results)} results.")
    ok(f"search returned {len(results)} trip(s), main trip is in there")

    # ---- 11: admin pricing update (idempotent create-or-update) ----
    step("11. Admin updating route pricing (Douala->Yaoundé, Comfort)")
    new_price = float(trip["price_per_seat"]) + 500
    updated = parse_or_fail(
        requests.post(
            f"{BASE_URL}/admin/route-pricing", headers=auth_headers(admin_token),
            json={
                "origin_city_id": cities["Douala"], "destination_city_id": cities["Yaoundé"],
                "vehicle_category_id": categories["Comfort"], "price_per_seat": new_price,
            },
        ),
        "admin route-pricing update",
    )
    if float(updated["price_per_seat"]) != new_price:
        fail(f"Price update didn't stick. Expected {new_price}, got {updated['price_per_seat']}")
    ok(f"price updated to {updated['price_per_seat']} (existing trips keep their snapshotted price, unaffected)")

    # ---- 12: force-pay the main booking so we can test post-payment features ----
    step("12. [TEST-ONLY] Forcing the main booking to 'paid' (bypassing real payment)")
    force_mark_paid(booking["id"], booking["price_total"])
    ok("booking forced to paid — real payment still untested by this script, see README")

    # ---- 13: chat ----
    step("13. Chat — driver and passenger exchange messages")
    parse_or_fail(
        requests.post(f"{BASE_URL}/trips/{trip['id']}/chat/messages", headers=auth_headers(driver_token),
                      json={"content": "Meeting point is Deido, near the market."}),
        "driver send message",
    )
    parse_or_fail(
        requests.post(f"{BASE_URL}/trips/{trip['id']}/chat/messages", headers=auth_headers(passenger_token),
                      json={"content": "Got it, see you at 8."}),
        "passenger send message",
    )
    messages = parse_or_fail(
        requests.get(f"{BASE_URL}/trips/{trip['id']}/chat/messages", headers=auth_headers(passenger_token)),
        "list messages",
    )
    if len(messages) < 2:
        fail(f"Expected at least 2 messages, got {len(messages)}")
    ok(f"{len(messages)} messages in the chat")

    # ---- 14: live location ----
    step("14. Live location — driver pushes position, passenger reads it")
    parse_or_fail(
        requests.post(f"{BASE_URL}/trips/{trip['id']}/location", headers=auth_headers(driver_token),
                      json={"latitude": 4.0511, "longitude": 9.7679}),
        "driver push location",
    )
    loc = parse_or_fail(
        requests.get(f"{BASE_URL}/trips/{trip['id']}/location/driver", headers=auth_headers(passenger_token)),
        "passenger read driver location",
    )
    ok(f"passenger sees driver at ({loc['latitude']}, {loc['longitude']})")

    # ---- 15: check-in ----
    step("15. Passenger check-in")
    parse_or_fail(
        requests.post(f"{BASE_URL}/trips/{trip['id']}/checkin", headers=auth_headers(passenger_token)),
        "check-in",
    )
    ok("check-in recorded, driver notified")

    # ---- 16: SOS ----
    step("16. SOS alert")
    sos = parse_or_fail(
        requests.post(f"{BASE_URL}/trips/{trip['id']}/sos", headers=auth_headers(passenger_token),
                      json={"latitude": 4.05, "longitude": 9.77}),
        "SOS",
    )
    ok(f"SOS alert id={sos['id']}, status={sos['status']}")

    # ---- 17: complete the trip ----
    step("17. Driver marks the main trip completed (triggers payout)")
    completed = parse_or_fail(
        requests.patch(f"{BASE_URL}/trips/{trip['id']}/complete", headers=auth_headers(driver_token)),
        "complete trip",
    )
    ok(f"trip status={completed['status']}, payout_amount={completed['payout_amount']}")

    # ---- 18: ratings ----
    step("18. Ratings — passenger rates driver, driver rates passenger")
    review1 = parse_or_fail(
        requests.post(f"{BASE_URL}/trips/{trip['id']}/reviews", headers=auth_headers(passenger_token),
                      json={"stars": 5, "comment": "Smooth ride, on time.", "emoji_reaction": "🙂"}),
        "passenger reviews driver",
    )
    ok(f"passenger->driver review id={review1['id']}, stars={review1['stars']}")

    review2 = parse_or_fail(
        requests.post(f"{BASE_URL}/trips/{trip['id']}/reviews", headers=auth_headers(driver_token),
                      json={"stars": 4, "comment": "Punctual passenger.", "reviewee_id": passenger_id}),
        "driver reviews passenger",
    )
    ok(f"driver->passenger review id={review2['id']}, stars={review2['stars']}")

    summary = parse_or_fail(requests.get(f"{BASE_URL}/users/{passenger_id}/reviews"), "GET passenger reviews")
    ok(f"passenger's public profile shows average {summary['average_stars']} stars from {summary['total_reviews']} review(s)")

    # ---- 19: passenger cancellation ----
    step("19. SCENARIO B — passenger cancels a booking")
    trip_b = create_trip(driver_token, vehicle["id"], locations["Akwa"], locations["Bastos"], seats=2)
    booking_b = book_and_force_pay(passenger_token, trip_b["id"])
    cancel_result = parse_or_fail(
        requests.patch(f"{BASE_URL}/bookings/{booking_b['id']}/cancel", headers=auth_headers(passenger_token)),
        "passenger cancel booking",
    )
    ok(f"cancelled: fee_charged={cancel_result['fee_charged']}, refund_amount={cancel_result['refund_amount']}")

    # ---- 20: driver cancellation + rebook ----
    step("20. SCENARIO C — driver cancels a trip, passenger rebooks")
    trip_c1 = create_trip(driver_token, vehicle["id"], locations["Bonaberi"], locations["Poste Centrale"], seats=2)
    booking_c1 = book_and_force_pay(passenger_token, trip_c1["id"])
    trip_c2 = create_trip(driver_token, vehicle["id"], locations["Bonaberi"], locations["Poste Centrale"], seats=2)

    driver_cancel_result = parse_or_fail(
        requests.patch(f"{BASE_URL}/trips/{trip_c1['id']}/cancel", headers=auth_headers(driver_token)),
        "driver cancel trip",
    )
    ok(f"driver cancelled trip, {driver_cancel_result['passengers_affected']} passenger(s) affected")

    rebook_result = parse_or_fail(
        requests.patch(f"{BASE_URL}/bookings/{booking_c1['id']}/rebook", headers=auth_headers(passenger_token),
                       json={"new_trip_id": trip_c2["id"]}),
        "rebook",
    )
    ok(f"rebooked onto new booking id={rebook_result['new_booking_id']}, status={rebook_result['status']}")

    # ---- 21: no-show ----
    step("21. SCENARIO D — driver marks a passenger as no-show")
    trip_d = create_trip(driver_token, vehicle["id"], locations["Bepanda"], locations["Ngoa-Ekelle"], seats=2)
    booking_d = book_and_force_pay(passenger_token, trip_d["id"])
    no_show_result = parse_or_fail(
        requests.patch(f"{BASE_URL}/bookings/{booking_d['id']}/mark-no-show", headers=auth_headers(driver_token)),
        "mark no-show",
    )
    ok(f"booking status={no_show_result['status']}")

    print("\n=== ALL STEPS PASSED (21/21) ===")
    print(f"Admin token:     {admin_token}")
    print(f"Driver token:    {driver_token}")
    print(f"Passenger token: {passenger_token}")
    print(f"Main trip id:    {trip['id']} (completed)")
    print("\nNOTE: real Mobile Money payment/payout still isn't covered by")
    print("this script — see the earlier manual /docs steps for that, using")
    print("a passenger account on YOUR real phone number, not these fake ones.")
    print("Step 12 force-marked a booking 'paid' directly in the database —")
    print("a TEST-ONLY shortcut that must never exist in the real app.")


if __name__ == "__main__":
    main()
