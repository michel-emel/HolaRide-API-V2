from typing import Optional

from app import models


def get_participant_role(db, trip: models.Trip, user: models.User) -> Optional[str]:
    """
    Returns 'driver', 'passenger', or None.

    A passenger only counts once they've PAID — this is what enforces
    "chat/location/reviews unlock only after payment" everywhere that
    matters, without repeating that check in every single endpoint.
    """
    if trip.driver_id == user.id:
        return "driver"

    paid_booking = (
        db.query(models.Booking)
        .filter(
            models.Booking.trip_id == trip.id,
            models.Booking.passenger_id == user.id,
            models.Booking.status.in_(("paid", "completed")),
        )
        .first()
    )
    if paid_booking:
        return "passenger"

    return None
