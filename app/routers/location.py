from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import get_current_user
from app.services import notifications
from app.services.trip_access import get_participant_role
from app.logging_config import get_logger

logger = get_logger("location")

router = APIRouter(prefix="/trips", tags=["location"])


def _require_participant(db: Session, trip_id: UUID, user: models.User):
    """Internal helper. Raises 403 unless the user is the driver or a paid passenger; returns (trip, role)."""
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    role = get_participant_role(db, trip, user)
    if not role:
        raise HTTPException(status_code=403, detail="You're not part of this trip")
    return trip, role


@router.post("/{trip_id}/location")
def update_location(
    trip_id: UUID,
    payload: schemas.LocationUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Pushes the caller's current GPS position for a trip, overwriting their last known one."""
    trip, role = _require_participant(db, trip_id, user)

    loc = (
        db.query(models.LiveLocation)
        .filter(models.LiveLocation.trip_id == trip_id, models.LiveLocation.user_id == user.id)
        .first()
    )
    is_first_share = loc is None  # True when sharing starts for the first time

    if loc:
        loc.latitude = payload.latitude
        loc.longitude = payload.longitude
        loc.updated_at = datetime.now(timezone.utc)
    else:
        loc = models.LiveLocation(
            trip_id=trip_id, user_id=user.id, latitude=payload.latitude, longitude=payload.longitude
        )
        db.add(loc)
    db.commit()

    # Only notify once, the first time someone starts sharing their location —
    # not on every subsequent GPS update (which would spam the participants).
    if is_first_share and role == "driver":
        # Driver started sharing → notify all paid passengers.
        passengers = (
            db.query(models.Booking)
            .filter(
                models.Booking.trip_id == trip_id,
                models.Booking.status.in_(("paid", "completed")),
            )
            .all()
        )
        for booking in passengers:
            notifications.notify_user(
                db, booking.passenger_id, "driver_location_shared",
                "Driver is sharing their location",
                "Your driver has started sharing their live location. Open the trip to track them.",
                reference_id=trip_id,
            )

    return {"status": "updated"}


@router.get("/{trip_id}/location/driver", response_model=schemas.LiveLocationOut)
def get_driver_location(trip_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Returns the driver's most recently pushed position. 404 if the driver hasn't shared location yet.

    Kept for backward compatibility — GET /{trip_id}/locations below is the
    more complete version (every participant, not just the driver) and is
    what the app actually uses now."""
    trip, _ = _require_participant(db, trip_id, user)
    loc = (
        db.query(models.LiveLocation)
        .filter(models.LiveLocation.trip_id == trip.id, models.LiveLocation.user_id == trip.driver_id)
        .first()
    )
    if not loc:
        raise HTTPException(status_code=404, detail="Driver hasn't shared their location yet")
    return loc


@router.get("/{trip_id}/locations", response_model=List[schemas.ParticipantLocationOut])
def list_locations(trip_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """
    Returns the most recently shared position for EVERY participant on
    this trip who has shared one — the driver AND any paid passenger,
    not just the driver. This is what makes location sharing genuinely
    bidirectional: anyone on the trip (driver or passenger) can see
    everyone else who's currently sharing, not only "driver pushes, one
    passenger reads." The push side (update_location above) already
    worked this way for any participant; this read endpoint was the
    actual missing piece.
    """
    trip, _ = _require_participant(db, trip_id, user)
    locs = db.query(models.LiveLocation).filter(models.LiveLocation.trip_id == trip.id).all()

    results = []
    for loc in locs:
        participant = db.query(models.User).filter(models.User.id == loc.user_id).first()
        if not participant:
            continue
        results.append(
            schemas.ParticipantLocationOut(
                user_id=loc.user_id,
                role="driver" if loc.user_id == trip.driver_id else "passenger",
                first_name=participant.first_name,
                last_name=participant.last_name,
                latitude=float(loc.latitude),
                longitude=float(loc.longitude),
                updated_at=loc.updated_at,
            )
        )
    return results


@router.post("/{trip_id}/checkin")
def checkin(trip_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Passenger-only. Confirms arrival at the pickup point; just notifies the driver, no stored state."""
    trip, role = _require_participant(db, trip_id, user)
    if role != "passenger":
        raise HTTPException(status_code=403, detail="Only a passenger can check in")

    notifications.notify_user(
        db, trip.driver_id, "passenger_checkin", "A passenger has arrived",
        f"{user.first_name or user.phone_number} checked in as arrived.",
    )
    return {"status": "checked_in"}


@router.post("/{trip_id}/sos", response_model=schemas.SOSOut)
def trigger_sos(
    trip_id: UUID,
    payload: schemas.SOSCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Triggers an SOS alert for either the driver or a passenger. Logs it
    loudly server-side and notifies whoever else is on the trip.
    See app/routers/location.py module notes for what's still missing
    (a real emergency-contact pipeline) before this is production-grade.
    """
    trip, role = _require_participant(db, trip_id, user)

    alert = models.SOSAlert(
        trip_id=trip.id, triggered_by=user.id, latitude=payload.latitude, longitude=payload.longitude
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    logger.warning(f"[SOS ALERT] trip={trip.id} triggered_by={user.id} role={role} lat={payload.latitude} lon={payload.longitude}")

    if role == "passenger":
        notify_ids = [trip.driver_id]
    else:
        notify_ids = [
            b.passenger_id for b in db.query(models.Booking).filter(
                models.Booking.trip_id == trip.id, models.Booking.status.in_(("paid", "completed"))
            ).all()
        ]
    for uid in notify_ids:
        notifications.notify_user(db, uid, "sos_alert", "SOS Alert", "Someone on your trip triggered an SOS alert.")

    return alert