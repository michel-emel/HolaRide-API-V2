from datetime import date as date_type, datetime, time as time_type, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, and_
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
    A driver can only have ONE active (published) trip at a time — they
    must complete or cancel it before posting a new one.
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

    # A driver can only have 1 active (published) trip at a time.
    # Once it's completed or cancelled, they can post a new one.
    active_count = (
        db.query(models.Trip)
        .filter(
            models.Trip.driver_id == driver.id,
            models.Trip.status == "published",
        )
        .count()
    )
    if active_count >= 1:
        raise HTTPException(
            status_code=400,
            detail="You already have an active trip — complete or cancel it before posting a new one.",
        )

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
        price_per_seat=price,
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
    departure_city: Optional[str] = None,
    destination_city_param: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """
    Returns published trips that haven't departed yet.
    For today's date, only trips whose departure time is still in the
    future are included — past trips are never shown.
    Accepts both origin_city/destination_city and departure_city/destination_city
    parameter names for compatibility.
    """
    # Normalise parameter names (web sends departure_city, app sends origin_city)
    dep_city  = departure_city or origin_city
    dest_city = destination_city_param or destination_city

    if bool(dep_city) != bool(dest_city):
        raise HTTPException(status_code=400, detail="Provide both departure and destination city, or neither")

    # Only show trips that haven't departed yet.
    today    = date_type.today()
    now_time = datetime.now(timezone.utc).time().replace(tzinfo=None)

    query = db.query(models.Trip).filter(
        models.Trip.status == "published",
        models.Trip.available_seats > 0,
        or_(
            models.Trip.departure_date > today,
            and_(
                models.Trip.departure_date == today,
                models.Trip.departure_time >= now_time,
            ),
        ),
    )

    if dep_city and dest_city:
        origin = db.query(models.City).filter(models.City.name == dep_city).first()
        destination = db.query(models.City).filter(models.City.name == dest_city).first()
        if not origin or not destination:
            return []

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
            if result["status"] == "rejected":
                payout.status = "failed"
            db.commit()
        except Exception as exc:
            payout.status = "failed"
            db.commit()
            raise HTTPException(status_code=502, detail=f"Could not reach the payout provider: {exc}")

    return {"trip_id": trip.id, "status": trip.status, "payout_amount": payout_total}