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