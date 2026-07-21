import re
from datetime import date, datetime, time
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

CAMEROON_PHONE_PATTERN = re.compile(r"^\+2376\d{8}$")


def _normalize_cameroon_phone(value: str) -> str:
    """
    Fixes the most common ways people actually type a Cameroon number,
    instead of rejecting anything that isn't already perfectly formatted:
      "237691234567"   -> "+237691234567"  (missing +)
      "00237691234567" -> "+237691234567"  (00 instead of +)
      "0691234567"     -> "+237691234567"  (local format with leading 0)
      "691234567"      -> "+237691234567"  (bare 9-digit number)
    """
    value = value.strip().replace(" ", "").replace("-", "")
    if value.startswith("00237"):
        return "+237" + value[5:]
    if value.startswith("237") and not value.startswith("+"):
        return "+" + value
    if value.startswith("0") and len(value) == 10:
        return "+237" + value[1:]
    if not value.startswith("+") and len(value) == 9:
        return "+237" + value
    return value


def _validate_cameroon_phone(value: str) -> str:
    normalized = _normalize_cameroon_phone(value)
    if not CAMEROON_PHONE_PATTERN.match(normalized):
        raise ValueError(
            "Phone number must be a Cameroon mobile number in the format "
            "+237 followed by 9 digits starting with 6, e.g. +237691234567"
        )
    return normalized


# ---- Auth ----

class OTPRequest(BaseModel):
    phone_number: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_cameroon_phone(v)


class OTPVerify(BaseModel):
    phone_number: str
    code: str
    # Only used the FIRST time a phone number verifies (i.e. registration).
    # Ignored on every login after that — see app/routers/auth.py.
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_cameroon_phone(v)

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{6}", v):
            raise ValueError("Code must be exactly 6 digits")
        return v


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


# ---- Trips ----

class TripCreate(BaseModel):
    vehicle_id: UUID
    departure_location_id: UUID
    destination_location_id: UUID
    departure_date: date
    departure_time: time
    available_seats: int = Field(gt=0)


class TripOut(BaseModel):
    id: UUID
    driver_id: UUID
    driver_first_name: Optional[str] = None
    driver_last_name: Optional[str] = None
    departure_city: str
    departure_location: str
    destination_city: str
    destination_location: str
    departure_date: date
    departure_time: time
    price_per_seat: float
    available_seats: int
    vehicle_category: str
    vehicle_brand: Optional[str] = None
    vehicle_model: Optional[str] = None
    status: str
    driver_rating_average: Optional[float] = None
    driver_rating_count: int = 0


class TripPricePreview(BaseModel):
    """Response for GET /trips/price-preview — just the number a
    driver would get if they published this exact route + vehicle
    combination right now. Nothing is created or snapshotted."""
    price_per_seat: float


# ---- Bookings ----

class BookingCreate(BaseModel):
    seats_booked: int = Field(gt=0)
    payment_type: Literal["full", "partial_80"] = "full"


class BookingOut(BaseModel):
    id: UUID
    trip_id: UUID
    seats_booked: int
    price_total: float
    payment_type: str
    amount_paid: float
    outstanding_balance: float
    status: str


class DriverBookingOut(BaseModel):
    """
    Same as BookingOut, plus enough passenger identity for a driver to
    actually act on a request — accept/reject only takes a booking id,
    but a human deciding whether to accept needs to know WHO is asking.
    Only ever returned to the trip's own driver (see
    GET /trips/{trip_id}/bookings), never to anyone else, so exposing
    a phone number here is safe.
    """
    id: UUID
    trip_id: UUID
    seats_booked: int
    price_total: float
    payment_type: str
    amount_paid: float
    outstanding_balance: float
    status: str
    created_at: datetime
    passenger_first_name: Optional[str] = None
    passenger_last_name: Optional[str] = None
    passenger_phone: str
    passenger_rating_average: Optional[float] = None
    passenger_rating_count: int = 0


# ---- Admin: geography ----

class CityCreate(BaseModel):
    name: str


class CityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str


class LocationCreate(BaseModel):
    city_id: UUID
    name: str


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    city_id: UUID
    name: str


class LocationSearchResult(BaseModel):
    id: UUID
    name: str
    city_id: UUID
    city_name: str


# ---- Admin: vehicle categories & approval ----

class VehicleCategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None


class VehicleCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: Optional[str] = None


class VehicleApproval(BaseModel):
    verification_status: Literal["approved", "rejected"]
    vehicle_category_id: Optional[UUID] = None


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    driver_id: UUID
    brand: str
    model: str
    plate_number: str
    total_seats: int
    verification_status: str
    vehicle_category_id: Optional[UUID] = None
    photo_urls: list[str] = []


# ---- Admin: route pricing ----

class RoutePricingCreate(BaseModel):
    origin_city_id: UUID
    destination_city_id: UUID
    vehicle_category_id: UUID
    price_per_seat: float = Field(gt=0)


class RoutePricingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    route_id: UUID
    vehicle_category_id: UUID
    price_per_seat: float


# ---- Admin: cancellation policy tiers ----

class CancellationTierCreate(BaseModel):
    min_hours_before: int
    max_hours_before: Optional[int] = None
    fee_percentage: float = Field(ge=0, le=100)


class CancellationTierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    min_hours_before: int
    max_hours_before: Optional[int] = None
    fee_percentage: float


# ---- Cancellations & rebooking ----

class RebookRequest(BaseModel):
    new_trip_id: UUID


# ---- Driver vehicle registration ----

class VehicleCreate(BaseModel):
    brand: str
    model: str
    year: Optional[int] = None
    color: Optional[str] = None
    plate_number: str
    total_seats: int = Field(gt=0)


# ---- User profile ----

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    phone_number: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None


# ---- Chat ----

class MessageCreate(BaseModel):
    content: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    chat_id: UUID
    sender_id: Optional[UUID] = None
    content: Optional[str] = None
    message_type: str
    created_at: datetime
    sender_first_name: Optional[str] = None
    sender_last_name: Optional[str] = None


# ---- Live location & SOS ----

class LocationUpdate(BaseModel):
    latitude: float
    longitude: float


class LiveLocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    latitude: float
    longitude: float
    updated_at: datetime


class ParticipantLocationOut(BaseModel):
    """
    Response for GET /trips/{trip_id}/locations — one entry per
    participant (driver or any paid passenger) who's currently
    sharing their position. This is what makes location sharing
    genuinely bidirectional: every participant can see every other
    participant, not just "driver shares, one passenger reads."
    """
    user_id: UUID
    role: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    latitude: float
    longitude: float
    updated_at: datetime


class SOSCreate(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class SOSOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    trip_id: UUID
    triggered_by: UUID
    status: str
    created_at: datetime


# ---- Ratings ----

class ReviewCreate(BaseModel):
    stars: int = Field(ge=1, le=5)
    comment: Optional[str] = None
    emoji_reaction: Optional[str] = None
    # Only needed when the reviewer is the DRIVER (there could be several
    # passengers on a trip, so the driver has to say which one). A
    # passenger reviewing the driver never needs to set this — it's
    # worked out automatically from the trip.
    reviewee_id: Optional[UUID] = None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    trip_id: UUID
    reviewer_id: UUID
    reviewee_id: UUID
    reviewer_role: str
    stars: int
    comment: Optional[str] = None
    emoji_reaction: Optional[str] = None
    created_at: datetime
    reviewer_first_name: Optional[str] = None
    reviewer_last_name: Optional[str] = None


class ReviewSummary(BaseModel):
    average_stars: float
    total_reviews: int
    reviews: list[ReviewOut]


class PendingReviewOut(BaseModel):
    """
    One entry per person the CALLER still needs to review for a given
    completed trip — a passenger only ever has the driver to review
    (one entry, at most); a driver has one entry per passenger who
    paid and hasn't been reviewed yet. Empty list means there's
    nothing left to rate.
    """
    user_id: UUID
    role: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None


# ---- My bookings (passenger booking history, with trip context) ----

class MyBookingOut(BaseModel):
    id: UUID
    trip_id: UUID
    seats_booked: int
    price_total: float
    payment_type: str
    amount_paid: float
    outstanding_balance: float
    status: str
    created_at: datetime
    departure_city: str
    departure_location: str
    destination_city: str
    destination_location: str
    departure_date: date
    departure_time: time
    # ✅ NOUVEAU : le statut du TRIP lui-même (published/ongoing/completed/
    # cancelled/full), distinct de `status` ci-dessus qui est celui du
    # BOOKING (paid/completed/cancelled/...). Les deux peuvent diverger
    # légitimement (ex: trip completed mais booking encore paid si un
    # solde reste dû) — le client a besoin des deux séparément pour
    # savoir, entre autres, si le partage de position live est encore
    # possible (ça ne dépend QUE du statut du trip, jamais du booking).
    trip_status: str


# ---- Notifications ----

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    type: str
    title: Optional[str] = None
    body: Optional[str] = None
    channel: Optional[str] = None
    status: str
    reference_id: Optional[UUID] = None
    read_at: Optional[datetime] = None
    created_at: datetime



# ---- Admin panel (web) — driver/city name joins for display ----

class AdminVehicleOut(BaseModel):
    """
    Like VehicleOut, but with the owning driver's name/phone joined
    in — used only by the admin panel's vehicle approval queue, where
    knowing WHO owns the vehicle is essential and nothing else in the
    API currently exposes it (there's no endpoint to list/look up
    users by id at all).
    """
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    driver_id: UUID
    brand: str
    model: str
    year: Optional[int] = None
    color: Optional[str] = None
    plate_number: str
    total_seats: int
    vehicle_category_id: Optional[UUID] = None
    verification_status: str
    created_at: Optional[datetime] = None
    driver_first_name: Optional[str] = None
    driver_last_name: Optional[str] = None
    driver_phone: Optional[str] = None


class AdminRoutePricingOut(BaseModel):
    """
    Like RoutePricingOut, but with the route's two city names (and
    IDs) plus the category name joined in — used only by the admin
    panel. RoutePricingOut alone only has route_id and
    vehicle_category_id, neither human-readable, and there's no
    endpoint that resolves a route back to its two cities.
    """
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    route_id: UUID
    vehicle_category_id: UUID
    price_per_seat: float
    origin_city_id: UUID
    destination_city_id: UUID
    origin_city_name: Optional[str] = None
    destination_city_name: Optional[str] = None
    vehicle_category_name: Optional[str] = None


class AdminUserOut(BaseModel):
    """Full account record for the admin user-management list — same fields as the users table itself."""
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    phone_number: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    phone_verified: bool
    is_active: bool
    created_at: Optional[datetime] = None


class UserStatusUpdate(BaseModel):
    """Body for PATCH /admin/users/{id}/status — suspend (false) or reactivate (true)."""
    is_active: bool


class AdminTripOut(BaseModel):
    """
    Admin-wide trip listing — every trip across every driver, with
    driver name/phone and resolved city + pickup-point names joined
    in, plus a booking count so admin can see at a glance whether
    deleting a given trip would also be erasing real passenger
    bookings.
    """
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    driver_id: UUID
    driver_first_name: Optional[str] = None
    driver_last_name: Optional[str] = None
    driver_phone: Optional[str] = None
    origin_city_name: Optional[str] = None
    origin_location_name: Optional[str] = None
    destination_city_name: Optional[str] = None
    destination_location_name: Optional[str] = None
    departure_date: date
    departure_time: time
    available_seats: int
    price_per_seat: float
    status: str
    booking_count: int = 0