from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import get_current_user
from app.services import payments_provider, storage
from app.services.trip_formatting import to_trip_out

router = APIRouter(prefix="/drivers/me", tags=["drivers"])


@router.post("/vehicle", response_model=schemas.VehicleOut)
def register_vehicle(
    payload: schemas.VehicleCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Anyone can register a vehicle — this is literally what "becoming
    a driver" means now, not something fixed back at signup. A driver
    profile (reliability score, etc.) gets created the first time
    someone does this; the actual ability to publish trips only
    unlocks once admin approves the vehicle (see require_driver()).
    """
    if db.query(models.Vehicle).filter(models.Vehicle.plate_number == payload.plate_number).first():
        raise HTTPException(status_code=400, detail="A vehicle with this plate number is already registered")

    if not db.query(models.DriverProfile).filter(models.DriverProfile.user_id == user.id).first():
        db.add(models.DriverProfile(user_id=user.id))
        db.commit()

    vehicle = models.Vehicle(driver_id=user.id, **payload.model_dump())
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.post("/vehicle/{vehicle_id}/photos", response_model=schemas.VehicleOut)
async def upload_vehicle_photos(
    vehicle_id: UUID,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Uploads one or more photos for a vehicle you own, to Supabase
    Storage. Each call ADDS to the vehicle's existing photo_urls list —
    it doesn't replace it. Useful both for admin verification (seeing
    the actual car before approving it) and later showing passengers
    what car to look for.
    """
    vehicle = (
        db.query(models.Vehicle)
        .filter(models.Vehicle.id == vehicle_id, models.Vehicle.driver_id == user.id)
        .first()
    )
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found for this driver")

    new_urls = []
    for file in files:
        content = await file.read()
        url = storage.upload_vehicle_photo(vehicle_id, file.filename, content, file.content_type)
        new_urls.append(url)

    vehicle.photo_urls = list(vehicle.photo_urls or []) + new_urls
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.get("/vehicles", response_model=List[schemas.VehicleOut])
def my_vehicles(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Lists every vehicle the current user has registered, with each one's approval status."""
    return db.query(models.Vehicle).filter(models.Vehicle.driver_id == user.id).all()


@router.get("/trips", response_model=List[schemas.TripOut])
def my_trips(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Lists every trip the current user has published as a driver, soonest first."""
    trips = (
        db.query(models.Trip)
        .filter(models.Trip.driver_id == user.id)
        .order_by(models.Trip.departure_date.desc(), models.Trip.departure_time.desc())
        .all()
    )
    return [to_trip_out(db, t) for t in trips]


@router.get("/payouts")
def my_payouts(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Lists the current user's payout history, most recent first."""
    payouts = db.query(models.Payout).filter(models.Payout.driver_id == user.id).order_by(
        models.Payout.created_at.desc()
    ).all()
    return [
        {"id": p.id, "trip_id": p.trip_id, "amount": float(p.amount), "status": p.status, "created_at": p.created_at}
        for p in payouts
    ]


@router.get("/payouts/{payout_id}/status")
def check_payout(
    payout_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    """Poll this until status is no longer 'pending' — same idea as the booking payment-status endpoint."""
    payout = db.query(models.Payout).filter(models.Payout.id == payout_id, models.Payout.driver_id == user.id).first()
    if not payout:
        raise HTTPException(status_code=404, detail="Payout not found")
    if payout.status != "pending" or not payout.provider_payout_id:
        return {"status": payout.status}

    provider_status = payments_provider.check_payout_status(payout.provider_payout_id)
    if provider_status == "COMPLETED":
        payout.status = "success"
        db.commit()
    elif provider_status == "FAILED":
        payout.status = "failed"
        db.commit()

    return {"status": payout.status}
