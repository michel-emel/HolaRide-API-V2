from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models


def get_trip_price(
    db: Session,
    departure_location_id: UUID,
    destination_location_id: UUID,
    vehicle: models.Vehicle,
):
    """
    Given a departure point, a destination point, and a vehicle:
    1. Find which cities those points belong to.
    2. Find the route between those cities.
    3. Find the price for that route + the vehicle's (admin-assigned) category.

    Returns (route, price_per_seat). Raises a clear error at whichever
    step is missing, so a driver gets a helpful message instead of a
    confusing 500 error.
    """
    departure = db.query(models.Location).filter(models.Location.id == departure_location_id).first()
    destination = db.query(models.Location).filter(models.Location.id == destination_location_id).first()
    if not departure or not destination:
        raise HTTPException(status_code=404, detail="Departure or destination location not found")

    route = (
        db.query(models.Route)
        .filter(
            models.Route.origin_city_id == departure.city_id,
            models.Route.destination_city_id == destination.city_id,
        )
        .first()
    )
    if not route:
        raise HTTPException(
            status_code=400,
            detail="This route isn't set up yet — ask admin to add it before publishing this trip",
        )

    if not vehicle.vehicle_category_id:
        raise HTTPException(
            status_code=400,
            detail="This vehicle hasn't been approved and categorized by admin yet",
        )

    pricing = (
        db.query(models.RoutePricing)
        .filter(
            models.RoutePricing.route_id == route.id,
            models.RoutePricing.vehicle_category_id == vehicle.vehicle_category_id,
        )
        .first()
    )
    if not pricing:
        raise HTTPException(
            status_code=400,
            detail="No price has been set for this route + vehicle category yet — ask admin",
        )

    return route, pricing.price_per_seat
