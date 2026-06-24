from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import get_current_user, require_driver
from app.services import cancellations, notifications
from app.services.chat_service import post_system_message
from app.services.trip_formatting import to_trip_out

router = APIRouter(prefix="/trips", tags=["bookings"])

# Separate router (no /trips prefix) for actions that operate on a
# booking directly, since the booking id alone is enough to find it.
actions_router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("/{trip_id}/bookings", response_model=schemas.BookingOut)
def create_booking(
    trip_id: UUID,
    payload: schemas.BookingCreate,
    db: Session = Depends(get_db),
    passenger: models.User = Depends(get_current_user),
):
    """
    Requests seats on a trip. payment_type "full" charges the whole price;
    "partial_80" only requires 80% now, with the remaining 20% owed
    later via POST /bookings/{id}/pay-balance. The booking starts as
    pending_driver_acceptance — the driver must call POST
    /bookings/{id}/accept before the passenger is allowed to pay at all.
    """
    # Lock the trip row so two passengers can't both book the last seat
    # at the same instant (a classic race condition without this).
    trip = (
        db.query(models.Trip)
        .filter(models.Trip.id == trip_id)
        .with_for_update()
        .first()
    )
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.status not in ("published", "boarding"):
        raise HTTPException(status_code=400, detail="This trip isn't open for booking")
    if payload.seats_booked > trip.available_seats:
        raise HTTPException(status_code=400, detail="Not enough seats available")

    # Max 2 active bookings per passenger for the same route, same day.
    # "Route" is the real routes.id (origin city + destination city) —
    # not the specific trip — so this blocks booking two DIFFERENT
    # trips on the same Yaoundé-Douala-on-the-25th, not just rebooking
    # the exact same trip twice. Cancelled/rejected bookings don't
    # count — those never actually became a real seat reservation.
    existing_count = (
        db.query(models.Booking)
        .join(models.Trip, models.Booking.trip_id == models.Trip.id)
        .filter(
            models.Booking.passenger_id == passenger.id,
            models.Trip.route_id == trip.route_id,
            models.Trip.departure_date == trip.departure_date,
            models.Booking.status.notin_(("cancelled", "rejected")),
        )
        .count()
    )
    if existing_count >= 2:
        raise HTTPException(
            status_code=400,
            detail="You already have 2 bookings on this route today — that's the daily limit per route.",
        )

    price_total = float(trip.price_per_seat) * payload.seats_booked

    if payload.payment_type == "partial_80":
        amount_due_now = round(price_total * 0.8, 2)
        outstanding = round(price_total - amount_due_now, 2)
    else:
        amount_due_now = price_total
        outstanding = 0.0

    booking = models.Booking(
        trip_id=trip.id,
        passenger_id=passenger.id,
        seats_booked=payload.seats_booked,
        price_total=price_total,
        payment_type=payload.payment_type,
        amount_paid=0,  # becomes amount_due_now once the Mobile Money payment is confirmed
        outstanding_balance=outstanding,
        status="pending_driver_acceptance",
    )

    # Seat is tentatively held the instant a request comes in, so nobody
    # else can grab it while the driver is still deciding. Restored if
    # the driver rejects — see reject_booking below.
    trip.available_seats -= payload.seats_booked
    if trip.available_seats == 0:
        trip.status = "full"

    db.add(booking)
    db.commit()
    db.refresh(booking)

    notifications.notify_user(
        db, trip.driver_id, "booking_request", "New booking request",
        f"A passenger wants {payload.seats_booked} seat(s) on your trip. Review it in My Trips.",
        channel="sms",
    )
    post_system_message(
        db, trip.id,
        f"{passenger.first_name or 'A passenger'} requested {payload.seats_booked} seat(s).",
    )

    # The actual Mobile Money charge happens separately, and only AFTER
    # the driver accepts — see POST /bookings/{id}/accept, and then
    # POST /bookings/{id}/initiate-payment in app/routers/payments.py.

    return schemas.BookingOut(
        id=booking.id,
        trip_id=booking.trip_id,
        seats_booked=booking.seats_booked,
        price_total=float(booking.price_total),
        payment_type=booking.payment_type,
        amount_paid=float(booking.amount_paid),
        outstanding_balance=float(booking.outstanding_balance),
        status=booking.status,
    )


@router.get("/{trip_id}/bookings", response_model=List[schemas.DriverBookingOut])
def list_trip_bookings(
    trip_id: UUID,
    db: Session = Depends(get_db),
    driver: models.User = Depends(require_driver()),
):
    """
    Driver-only. Lists every booking on one of your own trips, any
    status — this is what the Requests/Bookings tabs in trip
    management actually need to show anything real. 404s if the trip
    doesn't exist, 403s if it isn't yours — same two-step pattern as
    accept/reject/mark-no-show below, so a driver can't enumerate
    another driver's bookings just by guessing trip ids.
    """
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.driver_id != driver.id:
        raise HTTPException(status_code=403, detail="Not your trip")

    bookings = (
        db.query(models.Booking)
        .filter(models.Booking.trip_id == trip_id)
        .order_by(models.Booking.created_at.desc())
        .all()
    )

    results = []
    for b in bookings:
        passenger = db.query(models.User).filter(models.User.id == b.passenger_id).first()
        results.append(
            schemas.DriverBookingOut(
                id=b.id,
                trip_id=b.trip_id,
                seats_booked=b.seats_booked,
                price_total=float(b.price_total),
                payment_type=b.payment_type,
                amount_paid=float(b.amount_paid),
                outstanding_balance=float(b.outstanding_balance),
                status=b.status,
                created_at=b.created_at,
                passenger_first_name=passenger.first_name if passenger else None,
                passenger_last_name=passenger.last_name if passenger else None,
                passenger_phone=passenger.phone_number if passenger else "",
            )
        )
    return results


@actions_router.patch("/{booking_id}/cancel")
def cancel_booking(
    booking_id: UUID,
    db: Session = Depends(get_db),
    passenger: models.User = Depends(get_current_user),
):
    """
    Passenger cancels their own booking. The fee is a percentage of
    whatever was actually paid (set by admin via the cancellation
    policy tiers, based on how many hours before departure this is
    called) — never the full original price. Any unpaid 20% balance
    on a partial-payment booking is voided, not pursued.
    """
    booking = (
        db.query(models.Booking)
        .filter(models.Booking.id == booking_id, models.Booking.passenger_id == passenger.id)
        .first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status not in ("pending_driver_acceptance", "pending_payment", "paid"):
        raise HTTPException(status_code=400, detail=f"Booking can't be cancelled from status {booking.status}")

    trip = db.query(models.Trip).filter(models.Trip.id == booking.trip_id).first()
    departure_dt = datetime.combine(trip.departure_date, trip.departure_time, tzinfo=timezone.utc)
    hours_before = (departure_dt - datetime.now(timezone.utc)).total_seconds() / 3600
    if hours_before < 0:
        raise HTTPException(status_code=400, detail="This trip has already departed")

    fee_pct = cancellations.get_cancellation_fee_percentage(db, hours_before)
    # Fee is a % of what was ACTUALLY paid, not the full price — this one
    # formula works correctly for both full and partial payments, since
    # amount_paid already reflects whichever one it is.
    fee_charged = round(float(booking.amount_paid) * fee_pct / 100, 2)
    refund_amount = round(float(booking.amount_paid) - fee_charged, 2)

    booking.status = "cancelled"
    booking.outstanding_balance = 0  # any remaining 20% obligation is voided on cancellation

    trip.available_seats += booking.seats_booked
    if trip.status == "full":
        trip.status = "published"

    db.add(models.Cancellation(
        booking_id=booking.id, cancelled_by="passenger",
        reason="Passenger cancelled", fee_charged=fee_charged, refund_amount=refund_amount,
    ))
    db.commit()

    notifications.notify_user(
        db, passenger.id, "booking_cancelled", "Booking cancelled",
        f"Fee charged: {fee_charged} FCFA. Refunded: {refund_amount} FCFA.",
    )

    return {
        "booking_id": booking.id, "status": booking.status,
        "fee_charged": fee_charged, "refund_amount": refund_amount,
    }


@actions_router.patch("/{booking_id}/accept")
def accept_booking(
    booking_id: UUID,
    db: Session = Depends(get_db),
    driver: models.User = Depends(require_driver()),
):
    """
    Driver-only. Accepts a pending booking request, moving it to
    pending_payment — only after this can the passenger actually pay.
    """
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    trip = db.query(models.Trip).filter(models.Trip.id == booking.trip_id).first()
    if trip.driver_id != driver.id:
        raise HTTPException(status_code=403, detail="Not your trip")
    if booking.status != "pending_driver_acceptance":
        raise HTTPException(status_code=400, detail=f"Booking is already {booking.status}")

    booking.status = "pending_payment"
    db.commit()

    notifications.notify_user(
        db, booking.passenger_id, "booking_accepted", "Your booking was accepted",
        "The driver accepted your request — you can now pay for your seat.",
        channel="sms",
    )
    post_system_message(db, trip.id, "Booking request accepted.")
    return {"booking_id": booking.id, "status": booking.status}


@actions_router.patch("/{booking_id}/reject")
def reject_booking(
    booking_id: UUID,
    db: Session = Depends(get_db),
    driver: models.User = Depends(require_driver()),
):
    """
    Driver-only. Declines a pending booking request. No payment was
    ever taken at this stage, so there's nothing to refund — just
    frees the seat back up and notifies the passenger.
    """
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    trip = db.query(models.Trip).filter(models.Trip.id == booking.trip_id).first()
    if trip.driver_id != driver.id:
        raise HTTPException(status_code=403, detail="Not your trip")
    if booking.status != "pending_driver_acceptance":
        raise HTTPException(status_code=400, detail=f"Booking is already {booking.status}")

    booking.status = "rejected"
    trip.available_seats += booking.seats_booked
    if trip.status == "full":
        trip.status = "published"
    db.commit()

    notifications.notify_user(
        db, booking.passenger_id, "booking_rejected", "Your booking request was declined",
        "The driver wasn't able to accept your request for this trip. Try another trip on the same route.",
        channel="sms",
    )
    post_system_message(db, trip.id, "Booking request declined.")
    return {"booking_id": booking.id, "status": booking.status}


@actions_router.patch("/{booking_id}/mark-no-show")
def mark_no_show(
    booking_id: UUID,
    db: Session = Depends(get_db),
    driver: models.User = Depends(require_driver()),
):
    """
    Driver-only. Marks a paid passenger as a no-show. Whatever they
    already paid is forfeited with no refund, and any unpaid 20%
    balance (on a partial-payment booking) is voided rather than
    pursued further — same as a passenger-initiated cancellation.
    """
    booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    trip = db.query(models.Trip).filter(models.Trip.id == booking.trip_id).first()
    if trip.driver_id != driver.id:
        raise HTTPException(status_code=403, detail="Not your trip")
    if booking.status != "paid":
        raise HTTPException(status_code=400, detail="Only a paid booking can be marked as no-show")

    booking.status = "no_show"
    booking.outstanding_balance = 0  # remaining 20% obligation is voided on no-show too
    db.commit()

    notifications.notify_user(
        db, booking.passenger_id, "marked_no_show", "Marked as no-show",
        "You were marked as a no-show for this trip. The amount already paid is not refundable.",
    )
    return {"booking_id": booking.id, "status": booking.status}


@actions_router.patch("/{booking_id}/rebook")
def rebook(
    booking_id: UUID,
    payload: schemas.RebookRequest,
    db: Session = Depends(get_db),
    passenger: models.User = Depends(get_current_user),
):
    """
    Used after a driver cancels a trip: the passenger picks an
    alternative trip, and whatever they already paid transfers over.
    If the new trip costs more, the platform absorbs the difference —
    the passenger is never charged extra here.
    """
    old_booking = (
        db.query(models.Booking)
        .filter(models.Booking.id == booking_id, models.Booking.passenger_id == passenger.id)
        .first()
    )
    if not old_booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    cancellation = (
        db.query(models.Cancellation)
        .filter(models.Cancellation.booking_id == old_booking.id, models.Cancellation.cancelled_by == "driver")
        .first()
    )
    if not cancellation:
        raise HTTPException(status_code=400, detail="This booking wasn't cancelled by a driver, so it can't be rebooked")
    if cancellation.rebooked_to:
        raise HTTPException(status_code=400, detail="This booking was already rebooked")

    new_trip = db.query(models.Trip).filter(models.Trip.id == payload.new_trip_id).with_for_update().first()
    if not new_trip:
        raise HTTPException(status_code=404, detail="New trip not found")
    if new_trip.status not in ("published", "boarding"):
        raise HTTPException(status_code=400, detail="New trip isn't open for booking")
    if old_booking.seats_booked > new_trip.available_seats:
        raise HTTPException(status_code=400, detail="Not enough seats on the new trip")

    transferred_amount = float(old_booking.amount_paid)  # platform absorbs any price difference

    new_booking = models.Booking(
        trip_id=new_trip.id,
        passenger_id=passenger.id,
        seats_booked=old_booking.seats_booked,
        price_total=float(new_trip.price_per_seat) * old_booking.seats_booked,
        payment_type="full",
        amount_paid=transferred_amount,
        outstanding_balance=0,
        status="paid",
    )
    new_trip.available_seats -= old_booking.seats_booked
    if new_trip.available_seats == 0:
        new_trip.status = "full"

    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)

    cancellation.rebooked_to = new_booking.id
    db.commit()

    notifications.notify_user(
        db, passenger.id, "rebooked", "You're rebooked",
        "You're now booked on the new trip — no extra charge.",
    )

    return {
        "old_booking_id": old_booking.id,
        "new_booking_id": new_booking.id,
        "status": new_booking.status,
    }


# Separate router, no shared prefix with the other two — sits at /me/bookings,
# matching the "/me" pattern used elsewhere (GET /me, GET /drivers/me/...).
me_router = APIRouter(tags=["bookings"])


@me_router.get("/me/bookings", response_model=List[schemas.MyBookingOut])
def my_bookings(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Lists every booking the current user has made as a passenger, most recent first, with trip details included."""
    bookings = (
        db.query(models.Booking)
        .filter(models.Booking.passenger_id == user.id)
        .order_by(models.Booking.created_at.desc())
        .all()
    )

    results = []
    for booking in bookings:
        trip = db.query(models.Trip).filter(models.Trip.id == booking.trip_id).first()
        trip_out = to_trip_out(db, trip)
        results.append(
            schemas.MyBookingOut(
                id=booking.id,
                trip_id=booking.trip_id,
                seats_booked=booking.seats_booked,
                price_total=float(booking.price_total),
                payment_type=booking.payment_type,
                amount_paid=float(booking.amount_paid),
                outstanding_balance=float(booking.outstanding_balance),
                status=booking.status,
                created_at=booking.created_at,
                departure_city=trip_out.departure_city,
                departure_location=trip_out.departure_location,
                destination_city=trip_out.destination_city,
                destination_location=trip_out.destination_location,
                departure_date=trip_out.departure_date,
                departure_time=trip_out.departure_time,
            )
        )
    return results