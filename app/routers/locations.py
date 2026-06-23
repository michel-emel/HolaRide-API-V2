from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("/search", response_model=List[schemas.LocationSearchResult])
def search_locations(q: str, limit: int = 10, db: Session = Depends(get_db)):
    """
    Public, no login required. Searches by EITHER the pickup point's
    own name or its city's name, so typing "Yaoundé" surfaces every
    point inside it, and typing "Mvan" finds that point directly —
    both come back with the city attached for "(City, Point)" display.
    Used when creating a trip (picking departure/destination points)
    and when searching trips by city.
    """
    matches = (
        db.query(models.Location, models.City)
        .join(models.City, models.Location.city_id == models.City.id)
        .filter(
            or_(
                models.Location.name.ilike(f"%{q}%"),
                models.City.name.ilike(f"%{q}%"),
            )
        )
        .order_by(models.City.name, models.Location.name)
        .limit(limit)
        .all()
    )
    return [
        schemas.LocationSearchResult(id=loc.id, name=loc.name, city_id=city.id, city_name=city.name)
        for loc, city in matches
    ]
