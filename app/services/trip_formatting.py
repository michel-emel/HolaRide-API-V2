from sqlalchemy.orm import Session

from app import models, schemas


def to_trip_out(db: Session, trip: models.Trip) -> schemas.TripOut:
    """Assembles the city/location/category names for a trip's API response from their ids. Shared by trips.py and drivers.py."""
    dep_loc = db.query(models.Location).filter(models.Location.id == trip.departure_location_id).first()
    dest_loc = db.query(models.Location).filter(models.Location.id == trip.destination_location_id).first()
    dep_city = db.query(models.City).filter(models.City.id == dep_loc.city_id).first()
    dest_city = db.query(models.City).filter(models.City.id == dest_loc.city_id).first()
    vehicle = db.query(models.Vehicle).filter(models.Vehicle.id == trip.vehicle_id).first()
    category = (
        db.query(models.VehicleCategory)
        .filter(models.VehicleCategory.id == vehicle.vehicle_category_id)
        .first()
    )
    return schemas.TripOut(
        id=trip.id,
        departure_city=dep_city.name,
        departure_location=dep_loc.name,
        destination_city=dest_city.name,
        destination_location=dest_loc.name,
        departure_date=trip.departure_date,
        departure_time=trip.departure_time,
        price_per_seat=float(trip.price_per_seat),
        available_seats=trip.available_seats,
        vehicle_category=category.name,
        status=trip.status,
    )
