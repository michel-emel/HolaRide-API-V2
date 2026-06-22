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

@router.get("/vehicles/pending", response_model=List[schemas.VehicleOut])
def list_pending_vehicles(db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    """Admin-only. The approval queue — every vehicle awaiting a yes/no decision."""
    return db.query(models.Vehicle).filter(models.Vehicle.verification_status == "pending").all()


@router.patch("/vehicles/{vehicle_id}", response_model=schemas.VehicleOut)
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
    return vehicle


# ---- Route pricing ----

@router.post("/route-pricing", response_model=schemas.RoutePricingOut)
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
        return existing

    rp = models.RoutePricing(
        route_id=route.id,
        vehicle_category_id=payload.vehicle_category_id,
        price_per_seat=payload.price_per_seat,
    )
    db.add(rp)
    db.commit()
    db.refresh(rp)
    return rp


@router.get("/route-pricing", response_model=List[schemas.RoutePricingOut])
def list_route_pricing(db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    """Admin-only. Lists every route + category price currently configured."""
    return db.query(models.RoutePricing).all()


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
