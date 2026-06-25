from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import require_role

router = APIRouter(prefix="/admin", tags=["admin"])


# ---- Cities & locations ----

@router.post("/cities", response_model=schemas.CityOut)
def create_city(payload: schemas.CityCreate, db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    """Admin-only. Adds a new city (e.g. "Douala") that routes and pickup locations can be attached to."""
    if db.query(models.City).filter(models.City.name == payload.name).first():
        raise HTTPException(status_code=400, detail="City already exists")
    city = models.City(name=payload.name)
    db.add(city)
    db.commit()
    db.refresh(city)
    return city


@router.get("/cities", response_model=List[schemas.CityOut])
def list_cities(db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    """Admin-only. Lists every city currently configured."""
    return db.query(models.City).all()


@router.post("/locations", response_model=schemas.LocationOut)
def create_location(payload: schemas.LocationCreate, db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    """
    Admin-only. Adds a specific pickup/drop-off point within a city
    (e.g. "Deido" inside Douala). Drivers can only choose from points
    admin has already created here — no free-text location entry.
    """
    if not db.query(models.City).filter(models.City.id == payload.city_id).first():
        raise HTTPException(status_code=404, detail="City not found")
    loc = models.Location(city_id=payload.city_id, name=payload.name)
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


@router.get("/locations", response_model=List[schemas.LocationOut])
def list_locations(
    city_id: Optional[UUID] = None, db: Session = Depends(get_db), _=Depends(require_role("admin"))
):
    """Admin-only. Lists locations, optionally filtered down to one city via ?city_id=."""
    q = db.query(models.Location)
    if city_id:
        q = q.filter(models.Location.city_id == city_id)
    return q.all()


# ---- Vehicle categories ----

@router.post("/vehicle-categories", response_model=schemas.VehicleCategoryOut)
def create_vehicle_category(
    payload: schemas.VehicleCategoryCreate, db: Session = Depends(get_db), _=Depends(require_role("admin"))
):
    """
    Admin-only. Defines a new vehicle category (e.g. "Comfort", "Premium").
    Categories are what route pricing is actually keyed on — see
    /admin/route-pricing — not the vehicle itself.
    """
    if db.query(models.VehicleCategory).filter(models.VehicleCategory.name == payload.name).first():
        raise HTTPException(status_code=400, detail="Category already exists")
    cat = models.VehicleCategory(name=payload.name, description=payload.description)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.get("/vehicle-categories", response_model=List[schemas.VehicleCategoryOut])
def list_vehicle_categories(db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    """Admin-only. Lists every vehicle category."""
    return db.query(models.VehicleCategory).all()


# ---- Vehicle approval ----

def _to_admin_vehicle_out(db: Session, vehicle: models.Vehicle) -> schemas.AdminVehicleOut:
    """
    Joins in the owning driver's name/phone. The base Vehicle model
    only has driver_id — there's no endpoint anywhere that lists or
    looks up a user by id, so without this an admin reviewing the
    approval queue would have no way to know who they're approving.
    """
    driver = db.query(models.User).filter(models.User.id == vehicle.driver_id).first()
    return schemas.AdminVehicleOut(
        id=vehicle.id,
        driver_id=vehicle.driver_id,
        brand=vehicle.brand,
        model=vehicle.model,
        year=vehicle.year,
        color=vehicle.color,
        plate_number=vehicle.plate_number,
        total_seats=vehicle.total_seats,
        vehicle_category_id=vehicle.vehicle_category_id,
        verification_status=vehicle.verification_status,
        created_at=vehicle.created_at,
        driver_first_name=driver.first_name if driver else None,
        driver_last_name=driver.last_name if driver else None,
        driver_phone=driver.phone_number if driver else None,
    )


@router.get("/vehicles/pending", response_model=List[schemas.AdminVehicleOut])
def list_pending_vehicles(db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    """Admin-only. The approval queue — every vehicle awaiting a yes/no decision."""
    vehicles = db.query(models.Vehicle).filter(models.Vehicle.verification_status == "pending").all()
    return [_to_admin_vehicle_out(db, v) for v in vehicles]


@router.patch("/vehicles/{vehicle_id}", response_model=schemas.AdminVehicleOut)
def approve_vehicle(
    vehicle_id: UUID,
    payload: schemas.VehicleApproval,
    db: Session = Depends(get_db),
    _=Depends(require_role("admin")),
):
    """
    Admin-only. Approves or rejects a vehicle, and assigns its category
    if approving. This is the one action that actually unlocks driving
    for whoever owns the vehicle — see require_driver() in app/deps.py.
    """
    vehicle = db.query(models.Vehicle).filter(models.Vehicle.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    vehicle.verification_status = payload.verification_status
    if payload.vehicle_category_id:
        vehicle.vehicle_category_id = payload.vehicle_category_id
    db.commit()
    db.refresh(vehicle)
    return _to_admin_vehicle_out(db, vehicle)


# ---- Route pricing ----

def _to_admin_route_pricing_out(db: Session, rp: models.RoutePricing, route: models.Route) -> schemas.AdminRoutePricingOut:
    """
    Joins in the route's two city names (and IDs) plus the category
    name. RoutePricingOut on its own only has route_id and
    vehicle_category_id — neither is human-readable, and there's no
    endpoint that resolves a route back to its cities, so without this
    an admin viewing this list would see nothing but opaque UUIDs.
    """
    origin = db.query(models.City).filter(models.City.id == route.origin_city_id).first()
    destination = db.query(models.City).filter(models.City.id == route.destination_city_id).first()
    category = db.query(models.VehicleCategory).filter(models.VehicleCategory.id == rp.vehicle_category_id).first()
    return schemas.AdminRoutePricingOut(
        id=rp.id,
        route_id=rp.route_id,
        vehicle_category_id=rp.vehicle_category_id,
        price_per_seat=rp.price_per_seat,
        origin_city_id=route.origin_city_id,
        destination_city_id=route.destination_city_id,
        origin_city_name=origin.name if origin else None,
        destination_city_name=destination.name if destination else None,
        vehicle_category_name=category.name if category else None,
    )


@router.post("/route-pricing", response_model=schemas.AdminRoutePricingOut)
def set_route_pricing(
    payload: schemas.RoutePricingCreate, db: Session = Depends(get_db), _=Depends(require_role("admin"))
):
    """
    Admin-only. Sets the price-per-seat for a route + vehicle category
    combination. Creates the route if it doesn't exist yet, or updates
    the existing price if it does — safe to call repeatedly. Existing
    trips already published keep their original snapshotted price;
    only NEW trips created after this call use the updated price.
    """
    route = (
        db.query(models.Route)
        .filter(
            models.Route.origin_city_id == payload.origin_city_id,
            models.Route.destination_city_id == payload.destination_city_id,
        )
        .first()
    )
    if not route:
        route = models.Route(
            origin_city_id=payload.origin_city_id, destination_city_id=payload.destination_city_id
        )
        db.add(route)
        db.commit()
        db.refresh(route)

    existing = (
        db.query(models.RoutePricing)
        .filter(
            models.RoutePricing.route_id == route.id,
            models.RoutePricing.vehicle_category_id == payload.vehicle_category_id,
        )
        .first()
    )
    if existing:
        existing.price_per_seat = payload.price_per_seat
        db.commit()
        db.refresh(existing)
        return _to_admin_route_pricing_out(db, existing, route)

    rp = models.RoutePricing(
        route_id=route.id,
        vehicle_category_id=payload.vehicle_category_id,
        price_per_seat=payload.price_per_seat,
    )
    db.add(rp)
    db.commit()
    db.refresh(rp)
    return _to_admin_route_pricing_out(db, rp, route)


@router.get("/route-pricing", response_model=List[schemas.AdminRoutePricingOut])
def list_route_pricing(db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    """Admin-only. Lists every route + category price currently configured."""
    rows = db.query(models.RoutePricing).all()
    out = []
    for rp in rows:
        route = db.query(models.Route).filter(models.Route.id == rp.route_id).first()
        if not route:
            continue
        out.append(_to_admin_route_pricing_out(db, rp, route))
    return out


# ---- Cancellation policy tiers ----

@router.post("/cancellation-policy-tiers", response_model=schemas.CancellationTierOut)
def create_cancellation_tier(
    payload: schemas.CancellationTierCreate, db: Session = Depends(get_db), _=Depends(require_role("admin"))
):
    """
    Admin-only. Adds a time-based cancellation fee tier (e.g. "less
    than 6 hours before departure = 50% fee"). No-show is intentionally
    NOT configured here — it's a fixed 100% forfeiture handled in code.
    """
    tier = models.CancellationPolicyTier(**payload.model_dump())
    db.add(tier)
    db.commit()
    db.refresh(tier)
    return tier


@router.get("/cancellation-policy-tiers", response_model=List[schemas.CancellationTierOut])
def list_cancellation_tiers(db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    """Admin-only. Lists every cancellation fee tier, highest time-threshold first."""
    return (
        db.query(models.CancellationPolicyTier)
        .order_by(models.CancellationPolicyTier.min_hours_before.desc())
        .all()
    )


@router.patch("/cancellation-policy-tiers/{tier_id}", response_model=schemas.CancellationTierOut)
def update_cancellation_tier(
    tier_id: UUID,
    payload: schemas.CancellationTierCreate,
    db: Session = Depends(get_db),
    _=Depends(require_role("admin")),
):
    """Admin-only. Edits an existing cancellation fee tier's thresholds/percentage."""
    tier = db.query(models.CancellationPolicyTier).filter(models.CancellationPolicyTier.id == tier_id).first()
    if not tier:
        raise HTTPException(status_code=404, detail="Tier not found")
    tier.min_hours_before = payload.min_hours_before
    tier.max_hours_before = payload.max_hours_before
    tier.fee_percentage = payload.fee_percentage
    db.commit()
    db.refresh(tier)
    return tier


# ---- Trip management (admin) ----

def _to_admin_trip_out(db: Session, trip: models.Trip) -> schemas.AdminTripOut:
    driver = db.query(models.User).filter(models.User.id == trip.driver_id).first()
    route = db.query(models.Route).filter(models.Route.id == trip.route_id).first()
    origin = db.query(models.City).filter(models.City.id == route.origin_city_id).first() if route else None
    destination = (
        db.query(models.City).filter(models.City.id == route.destination_city_id).first() if route else None
    )
    booking_count = db.query(models.Booking).filter(models.Booking.trip_id == trip.id).count()
    return schemas.AdminTripOut(
        id=trip.id,
        driver_id=trip.driver_id,
        driver_first_name=driver.first_name if driver else None,
        driver_last_name=driver.last_name if driver else None,
        driver_phone=driver.phone_number if driver else None,
        origin_city_name=origin.name if origin else None,
        destination_city_name=destination.name if destination else None,
        departure_date=trip.departure_date,
        departure_time=trip.departure_time,
        available_seats=trip.available_seats,
        price_per_seat=trip.price_per_seat,
        status=trip.status,
        booking_count=booking_count,
    )


def _cascade_delete_trip(db: Session, trip: models.Trip):
    """
    Permanently deletes a trip and everything that references it —
    bookings, payments, cancellations, live locations, SOS alerts,
    reviews, its chat and every message in it, and any payouts already
    issued for it. This is IRREVERSIBLE and erases payment/payout
    history along with the trip — there's no soft-delete, no undo, and
    no refund issued automatically; if passengers already paid, that
    payment record is simply gone.

    Reports that mention this trip have their trip_id cleared instead
    of being deleted outright — a report is a moderation record about
    a PERSON's behavior, and erasing it just because the trip listing
    is gone would destroy safety history for no real reason. Same idea
    for driver reliability log entries: the score impact already
    happened and stays on the driver's record; only the link back to
    this specific trip is cleared.

    Does NOT commit — callers commit once, after this returns, so a
    failure partway through doesn't leave a half-deleted trip behind.
    """
    bookings = db.query(models.Booking).filter(models.Booking.trip_id == trip.id).all()
    booking_ids = [b.id for b in bookings]
    if booking_ids:
        # A cancellation can point at ANOTHER booking via rebooked_to —
        # clear that link first wherever it points at a booking we're
        # about to delete, regardless of which trip that cancellation
        # itself belongs to.
        db.query(models.Cancellation).filter(models.Cancellation.rebooked_to.in_(booking_ids)).update(
            {models.Cancellation.rebooked_to: None}, synchronize_session=False
        )
        db.query(models.Cancellation).filter(models.Cancellation.booking_id.in_(booking_ids)).delete(
            synchronize_session=False
        )
        db.query(models.Payment).filter(models.Payment.booking_id.in_(booking_ids)).delete(
            synchronize_session=False
        )
        db.query(models.Booking).filter(models.Booking.trip_id == trip.id).delete(synchronize_session=False)

    chat = db.query(models.TripChat).filter(models.TripChat.trip_id == trip.id).first()
    if chat:
        db.query(models.Message).filter(models.Message.chat_id == chat.id).delete(synchronize_session=False)
        db.delete(chat)

    db.query(models.LiveLocation).filter(models.LiveLocation.trip_id == trip.id).delete(synchronize_session=False)
    db.query(models.SOSAlert).filter(models.SOSAlert.trip_id == trip.id).delete(synchronize_session=False)
    db.query(models.Review).filter(models.Review.trip_id == trip.id).delete(synchronize_session=False)
    db.query(models.Payout).filter(models.Payout.trip_id == trip.id).delete(synchronize_session=False)
    db.query(models.Report).filter(models.Report.trip_id == trip.id).update(
        {models.Report.trip_id: None}, synchronize_session=False
    )
    db.query(models.DriverReliabilityLog).filter(models.DriverReliabilityLog.related_trip_id == trip.id).update(
        {models.DriverReliabilityLog.related_trip_id: None}, synchronize_session=False
    )

    db.delete(trip)


@router.get("/trips", response_model=List[schemas.AdminTripOut])
def list_all_trips(db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    """Admin-only. Every trip across every driver — for finding one to delete/moderate, not a search UI."""
    trips = db.query(models.Trip).order_by(models.Trip.departure_date.desc()).all()
    return [_to_admin_trip_out(db, t) for t in trips]


@router.delete("/trips/{trip_id}")
def delete_trip(trip_id: UUID, db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    """
    Admin-only. PERMANENTLY deletes a trip — see `_cascade_delete_trip`
    above for exactly what that takes with it. Irreversible.
    """
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    _cascade_delete_trip(db, trip)
    db.commit()
    return {"status": "deleted", "trip_id": trip_id}


# ---- User management (admin) ----

def _cascade_delete_user(db: Session, user: models.User):
    """
    Permanently deletes a user account and everything connected to it
    — irreversible, same caveats as `_cascade_delete_trip`. If this
    account is a driver, every trip they ever published is cascade-
    deleted the same way (payment/payout records included). If this
    account has bookings as a PASSENGER on other people's trips, those
    bookings are deleted too — but first the seats they took are
    credited back to that other trip's available_seats, the same way
    a normal cancellation would, so deleting one passenger doesn't
    leave some unrelated driver's trip permanently short on seats.

    Messages this user sent, reviews they're part of (either side),
    and reports they're part of (either side) are deleted outright
    rather than anonymized — a half-erased review or report with a
    "Deleted User" placeholder isn't meaningful to anyone, and the
    request was for a true delete, not a soft one.
    """
    own_trips = db.query(models.Trip).filter(models.Trip.driver_id == user.id).all()
    for trip in own_trips:
        _cascade_delete_trip(db, trip)

    passenger_bookings = db.query(models.Booking).filter(models.Booking.passenger_id == user.id).all()
    for booking in passenger_bookings:
        other_trip = db.query(models.Trip).filter(models.Trip.id == booking.trip_id).first()
        if other_trip and booking.status not in ("cancelled", "rejected"):
            other_trip.available_seats += booking.seats_booked
        db.query(models.Cancellation).filter(models.Cancellation.rebooked_to == booking.id).update(
            {models.Cancellation.rebooked_to: None}, synchronize_session=False
        )
        db.query(models.Cancellation).filter(models.Cancellation.booking_id == booking.id).delete(
            synchronize_session=False
        )
        db.query(models.Payment).filter(models.Payment.booking_id == booking.id).delete(synchronize_session=False)
        db.delete(booking)

    db.query(models.Vehicle).filter(models.Vehicle.driver_id == user.id).delete(synchronize_session=False)
    db.query(models.DriverProfile).filter(models.DriverProfile.user_id == user.id).delete(synchronize_session=False)
    db.query(models.Message).filter(models.Message.sender_id == user.id).delete(synchronize_session=False)
    db.query(models.LiveLocation).filter(models.LiveLocation.user_id == user.id).delete(synchronize_session=False)
    db.query(models.SOSAlert).filter(models.SOSAlert.triggered_by == user.id).delete(synchronize_session=False)
    db.query(models.Review).filter(
        (models.Review.reviewer_id == user.id) | (models.Review.reviewee_id == user.id)
    ).delete(synchronize_session=False)
    db.query(models.Report).filter(
        (models.Report.reporter_id == user.id) | (models.Report.reported_user_id == user.id)
    ).delete(synchronize_session=False)
    db.query(models.Notification).filter(models.Notification.user_id == user.id).delete(synchronize_session=False)
    db.query(models.DeviceToken).filter(models.DeviceToken.user_id == user.id).delete(synchronize_session=False)
    db.query(models.DriverReliabilityLog).filter(models.DriverReliabilityLog.driver_id == user.id).delete(
        synchronize_session=False
    )
    db.query(models.Payout).filter(models.Payout.driver_id == user.id).delete(synchronize_session=False)

    db.delete(user)


@router.get("/users", response_model=List[schemas.AdminUserOut])
def list_users(
    search: Optional[str] = None, db: Session = Depends(get_db), _=Depends(require_role("admin"))
):
    """Admin-only. Every account, optionally filtered by phone/first/last name via ?search=."""
    q = db.query(models.User)
    if search:
        like = f"%{search}%"
        q = q.filter(
            models.User.phone_number.ilike(like)
            | models.User.first_name.ilike(like)
            | models.User.last_name.ilike(like)
        )
    return q.order_by(models.User.created_at.desc()).all()


@router.patch("/users/{user_id}/status", response_model=schemas.AdminUserOut)
def set_user_status(
    user_id: UUID,
    payload: schemas.UserStatusUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_role("admin")),
):
    """Admin-only. Suspends (is_active=false) or reactivates (is_active=true) an account."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}")
def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_role("admin")),
):
    """
    Admin-only. PERMANENTLY deletes a user account — see
    `_cascade_delete_user` above for exactly what that takes with it.
    Irreversible.

    NOTE: assumes require_role("admin") returns the authenticated
    User, by analogy with require_driver()'s established pattern
    elsewhere in this codebase (every other admin endpoint in this
    file discards it as `_` since it never needed the value before
    now) — verify this works as expected; if require_role's actual
    signature differs, this is the one line that needs adjusting.

    An admin can't delete their own account through this endpoint —
    do that with direct SQL if it's ever genuinely needed, so a
    panel mis-click can't lock everyone out of admin entirely.
    """
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You can't delete your own account from here")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _cascade_delete_user(db, user)
    db.commit()
    return {"status": "deleted", "user_id": user_id}