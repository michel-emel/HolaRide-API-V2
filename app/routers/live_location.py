"""
Live location sharing for ongoing trips (Supabase Realtime transport).

Flow:
  1. Driver taps "Start trip"  → POST /trips/{id}/start   (published → ongoing)
  2. Both phones push GPS      → POST /trips/{id}/position (upsert, 1 row/user)
  3. Both phones read via Supabase Realtime (postgres_changes on
     live_locations), authorized by a short-lived token from
     GET /trips/{id}/realtime-token — signed with the SUPABASE JWT
     secret so RLS policies (auth.uid()) apply. The asymmetry
     (passenger sees driver only, driver sees everyone) is enforced by
     the RLS policies from migration 0009, NOT by the client.
  4. GET /trips/{id}/positions gives the last known points for the
     initial map render (same asymmetry, enforced here in code).

Writes only ever happen through this router (our DB role bypasses RLS;
clients have no INSERT/UPDATE policy at all), so positions can't be
forged by talking to Supabase directly.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from jose import jwt
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import get_db
from app.deps import get_current_user

router = APIRouter(prefix="/trips", tags=["live-location"])


# ── Schemas (local to this feature) ─────────────────────────────────

class PositionIn(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    heading: Optional[float] = Field(None, ge=0, lt=360)


class PositionOut(BaseModel):
    user_id: UUID
    role: str  # 'driver' | 'passenger'
    latitude: float
    longitude: float
    heading: Optional[float]
    updated_at: datetime


class RealtimeTokenOut(BaseModel):
    token: str
    expires_at: datetime
    table: str = "live_locations"


# ── Helpers ──────────────────────────────────────────────────────────

def _get_trip_or_404(db: Session, trip_id: UUID) -> models.Trip:
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


def _role_on_trip(db: Session, trip: models.Trip, user: models.User) -> Optional[str]:
    """'driver', 'passenger' (paid booking) or None."""
    if trip.driver_id == user.id:
        return "driver"
    paid = (
        db.query(models.Booking)
        .filter(
            models.Booking.trip_id == trip.id,
            models.Booking.passenger_id == user.id,
            models.Booking.status == "paid",
        )
        .first()
    )
    return "passenger" if paid else None


def _require_member(db: Session, trip: models.Trip, user: models.User) -> str:
    role = _role_on_trip(db, trip, user)
    if role is None:
        raise HTTPException(status_code=403, detail="You are not part of this trip")
    return role


# ── 1. Start the trip (driver only) ──────────────────────────────────

@router.post("/{trip_id}/start")
def start_trip(
    trip_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Driver taps "Start trip". published → ongoing.
    Location sharing (POST /position) only works while status is
    'ongoing', and RLS reads only matter during that window too.
    """
    trip = _get_trip_or_404(db, trip_id)
    if trip.driver_id != user.id:
        raise HTTPException(status_code=403, detail="Only the driver can start this trip")
    if trip.status == "ongoing":
        return {"status": "ongoing"}  # idempotent — double-tap safe
    if trip.status != "published":
        raise HTTPException(
            status_code=409,
            detail=f"Trip can't be started from status '{trip.status}'",
        )
    trip.status = "ongoing"
    db.commit()
    return {"status": "ongoing"}


# ── 2. Push a position (driver or paid passenger) ────────────────────

@router.post("/{trip_id}/position")
def push_position(
    trip_id: UUID,
    payload: PositionIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    trip = _get_trip_or_404(db, trip_id)
    _require_member(db, trip, user)

    if trip.status != "ongoing":
        raise HTTPException(status_code=409, detail="Location sharing is only active while the trip is ongoing")

    stmt = (
        pg_insert(models.LiveLocation)
        .values(
            trip_id=trip.id,
            user_id=user.id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            heading=payload.heading,
            updated_at=func.now(),
        )
        .on_conflict_do_update(
            constraint="uq_live_locations_trip_user",
            set_={
                "latitude": payload.latitude,
                "longitude": payload.longitude,
                "heading": payload.heading,
                "updated_at": func.now(),
            },
        )
    )
    db.execute(stmt)
    db.commit()
    return {"ok": True}


# ── 3. Short-lived Supabase Realtime token ───────────────────────────

@router.get("/{trip_id}/realtime-token", response_model=RealtimeTokenOut)
def realtime_token(
    trip_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Bridges our own auth to Supabase RLS: a token signed with the
    project's JWT secret, whose `sub` is our user_id — so `auth.uid()`
    in the RLS policies resolves to the same UUIDs our tables use.
    Valid 6h (covers any intercity trip); the app refetches if needed.
    """
    trip = _get_trip_or_404(db, trip_id)
    _require_member(db, trip, user)

    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_JWT_SECRET is not configured on the server",
        )

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=6)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "role": "authenticated",
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )
    return RealtimeTokenOut(token=token, expires_at=expires_at)


# ── 4. Last known positions (initial map render) ─────────────────────

@router.get("/{trip_id}/positions", response_model=List[PositionOut])
def get_positions(
    trip_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Same asymmetry as the RLS policies, enforced in code:
      - driver     → every position on the trip
      - passenger  → the driver's position only
    """
    trip = _get_trip_or_404(db, trip_id)
    role = _require_member(db, trip, user)

    q = db.query(models.LiveLocation).filter(models.LiveLocation.trip_id == trip.id)
    if role == "passenger":
        q = q.filter(models.LiveLocation.user_id == trip.driver_id)

    out: List[PositionOut] = []
    for row in q.all():
        out.append(PositionOut(
            user_id=row.user_id,
            role="driver" if row.user_id == trip.driver_id else "passenger",
            latitude=float(row.latitude),
            longitude=float(row.longitude),
            heading=float(row.heading) if row.heading is not None else None,
            updated_at=row.updated_at,
        ))
    return out