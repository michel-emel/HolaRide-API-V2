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

    # The driver's rating, so a passenger can see it before booking
    # without a separate request — joined in the same spirit as the
    # city/category names above.
    driver_reviews = db.query(models.Review).filter(models.Review.reviewee_id == trip.driver_id).all()
    driver_rating_average = (
        round(sum(r.stars for r in driver_reviews) / len(driver_reviews), 2) if driver_reviews else None
    )
    driver = db.query(models.User).filter(models.User.id == trip.driver_id).first()

    return schemas.TripOut(
        id=trip.id,
        driver_id=trip.driver_id,
        driver_first_name=driver.first_name if driver else None,
        driver_last_name=driver.last_name if driver else None,
        departure_city=dep_city.name,
        departure_location=dep_loc.name,
        destination_city=dest_city.name,
        destination_location=dest_loc.name,
        departure_date=trip.departure_date,
        departure_time=trip.departure_time,
        price_per_seat=float(trip.price_per_seat),
        available_seats=trip.available_seats,
        vehicle_category=category.name,
        vehicle_brand=vehicle.brand if vehicle else None,
        vehicle_model=vehicle.model if vehicle else None,
        status=trip.status,
        driver_rating_average=driver_rating_average,
        driver_rating_count=len(driver_reviews),
    )
