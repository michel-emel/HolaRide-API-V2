from datetime import date as date_type
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import require_driver
from app.services import cancellations, notifications, payments_provider
from app.services.pricing import get_trip_price
from app.services.trip_formatting import to_trip_out

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("", response_model=schemas.TripOut)
def create_trip(
    payload: schemas.TripCreate,
    db: Session = Depends(get_db),
    driver: models.User = Depends(require_driver()),
):
    """
    Driver-only (requires an admin-approved vehicle). Publishes a trip.
    The driver only picks vehicle, departure/destination points, date,
    time, and seats — price and vehicle category are both derived
    automatically from route + the vehicle's assigned category, then
    snapshotted onto the trip so later admin price changes don't
    retroactively affect it.
    """
    vehicle = (
        db.query(models.Vehicle)
        .filter(models.Vehicle.id == payload.vehicle_id, models.Vehicle.driver_id == driver.id)
        .first()
    )
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found for this driver")
    if vehicle.verification_status != "approved":
        raise HTTPException(status_code=400, detail="This vehicle isn't approved by admin yet")
    if payload.available_seats > vehicle.total_seats:
        raise HTTPException(status_code=400, detail="Available seats can't exceed the vehicle's total seats")

    # Max 2 active trips per driver at once. "Active" means not yet
    # completed or cancelled — a driver juggling more than 2 live
    # trips at a time is exactly the scenario this caps.
    active_count = (
        db.query(models.Trip)
        .filter(
            models.Trip.driver_id == driver.id,
            models.Trip.status.notin_(("completed", "cancelled")),
        )
        .count()
    )
    if active_count >= 2:
        raise HTTPException(
            status_code=400,
            detail="You already have 2 active trips — complete or cancel one before publishing another.",
        )

    # Driver never sets a category or a price — both are derived here.
    route, price = get_trip_price(db, payload.departure_location_id, payload.destination_location_id, vehicle)

    trip = models.Trip(
        driver_id=driver.id,
        vehicle_id=vehicle.id,
        route_id=route.id,
        departure_location_id=payload.departure_location_id,
        destination_location_id=payload.destination_location_id,
        departure_date=payload.departure_date,
        departure_time=payload.departure_time,
        available_seats=payload.available_seats,
        price_per_seat=price,   # snapshotted now — a later admin price change won't affect this trip
        status="published",
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return to_trip_out(db, trip)


@router.get("/search", response_model=List[schemas.TripOut])
def search_trips(
    origin_city: Optional[str] = None,
    destination_city: Optional[str] = None,
    departure_date: Optional[date_type] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """
    With both origin_city and destination_city: filters to that exact route
    (the original behavior). With NEITHER: just browses the soonest
    available published trips, for a "discovery feed" type screen (e.g.
    a home screen showing a few trips before the user has searched anything).
    """
    if bool(origin_city) != bool(destination_city):
        raise HTTPException(status_code=400, detail="Provide both origin_city and destination_city, or neither")

    query = db.query(models.Trip).filter(
        models.Trip.status == "published",
        models.Trip.available_seats > 0,
    )

    if origin_city and destination_city:
        origin = db.query(models.City).filter(models.City.name == origin_city).first()
        destination = db.query(models.City).filter(models.City.name == destination_city).first()
        if not origin or not destination:
            raise HTTPException(status_code=404, detail="City not found")

        route = (
            db.query(models.Route)
            .filter(
                models.Route.origin_city_id == origin.id,
                models.Route.destination_city_id == destination.id,
            )
            .first()
        )
        if not route:
            return []
        query = query.filter(models.Trip.route_id == route.id)

    if departure_date:
        query = query.filter(models.Trip.departure_date == departure_date)

    query = query.order_by(models.Trip.departure_date, models.Trip.departure_time).limit(limit)
    return [to_trip_out(db, t) for t in query.all()]


@router.get("/price-preview", response_model=schemas.TripPricePreview)
def preview_trip_price(
    vehicle_id: UUID,
    departure_location_id: UUID,
    destination_location_id: UUID,
    db: Session = Depends(get_db),
    driver: models.User = Depends(require_driver()),
):
    """
    Lets a driver see the price-per-seat for a route before actually
    publishing a trip, using the exact same pricing lookup create_trip
    uses (get_trip_price) — so this number can never drift out of sync
    with what the trip would actually be charged at. Same vehicle
    ownership/approval checks as create_trip, since price depends on
    the vehicle's assigned category. Nothing is created here.
    """
    vehicle = (
        db.query(models.Vehicle)
        .filter(models.Vehicle.id == vehicle_id, models.Vehicle.driver_id == driver.id)
        .first()
    )
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found for this driver")
    if vehicle.verification_status != "approved":
        raise HTTPException(status_code=400, detail="This vehicle isn't approved by admin yet")

    _, price = get_trip_price(db, departure_location_id, destination_location_id, vehicle)
    return schemas.TripPricePreview(price_per_seat=price)


@router.get("/{trip_id}", response_model=schemas.TripOut)
def get_trip(trip_id: UUID, db: Session = Depends(get_db)):
    """Public. Returns full details for a single trip."""
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return to_trip_out(db, trip)


@router.patch("/{trip_id}/cancel")
def cancel_trip(
    trip_id: UUID,
    db: Session = Depends(get_db),
    driver: models.User = Depends(require_driver()),
):
    """
    Driver-only. Cancels an entire trip. Every passenger with a paid
    booking gets notified and a Cancellation record (so they can later
    call /bookings/{id}/rebook onto an alternative); anyone who doesn't
    rebook is refunded in full. Also dings the driver's reliability score.
    """
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id, models.Trip.driver_id == driver.id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Trip is already {trip.status}")

    affected = db.query(models.Booking).filter(
        models.Booking.trip_id == trip.id, models.Booking.status == "paid"
    ).all()

    cancellations.apply_reliability_penalty(db, driver.id, trip.id, points=10, event_type="trip_cancelled")

    for booking in affected:
        refund_amount = float(booking.amount_paid)
        booking.status = "cancelled"
        booking.outstanding_balance = 0
        db.add(models.Cancellation(
            booking_id=booking.id, cancelled_by="driver",
            reason="Driver cancelled the trip", fee_charged=0, refund_amount=refund_amount,
        ))
        notifications.notify_user(
            db, booking.passenger_id, "trip_cancelled", "Your trip was cancelled by the driver",
            f"You've been refunded {refund_amount} FCFA. Search for another trip on this route, "
            f"or use the rebook option on this booking if one is offered.",
        )

    trip.status = "cancelled"
    db.commit()
    return {"trip_id": trip.id, "status": trip.status, "passengers_affected": len(affected)}


@router.patch("/{trip_id}/complete")
def complete_trip(
    trip_id: UUID,
    db: Session = Depends(get_db),
    driver: models.User = Depends(require_driver()),
):
    """
    Driver marks the trip as completed once it's actually finished.
    This is what triggers the driver's instant payout — for every
    booking that's paid or no_show on this trip, the driver gets
    paid the full price_total, regardless of whether a partial-payment
    passenger ever settled their remaining 20%.
    """
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id, models.Trip.driver_id == driver.id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.status == "completed":
        raise HTTPException(status_code=400, detail="Trip already marked completed")

    payable_bookings = db.query(models.Booking).filter(
        models.Booking.trip_id == trip.id, models.Booking.status.in_(("paid", "no_show"))
    ).all()

    payout_total = 0.0
    for booking in payable_bookings:
        payout_total += float(booking.price_total)
        if booking.status == "paid":
            booking.status = "completed"

    trip.status = "completed"
    db.commit()

    if payout_total > 0:
        payout = models.Payout(
            driver_id=driver.id, trip_id=trip.id, provider="pawapay", amount=payout_total, status="pending"
        )
        db.add(payout)
        db.commit()
        db.refresh(payout)

        try:
            result = payments_provider.disburse(driver.phone_number, payout_total)
            payout.provider_payout_id = result["provider_payout_id"]
            # Stays "pending" — PawaPay confirms the FINAL result later via
            # webhook (POST /payments/webhook/pawapay) or by polling
            # check_payout_status(). "ACCEPTED" from disburse() just means
            # the request was received, not that the driver has the money yet.
            if result["status"] == "rejected":
                payout.status = "failed"
            db.commit()
        except Exception as exc:
            payout.status = "failed"
            db.commit()
            raise HTTPException(status_code=502, detail=f"Could not reach the payout provider: {exc}")

    return {"trip_id": trip.id, "status": trip.status, "payout_amount": payout_total}