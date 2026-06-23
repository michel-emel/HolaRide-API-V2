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
    departure_city: str
    departure_location: str
    destination_city: str
    destination_location: str
    departure_date: date
    departure_time: time
    price_per_seat: float
    available_seats: int
    vehicle_category: str
    status: str


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


# ---- Live location & SOS ----

class LocationUpdate(BaseModel):
    latitude: float
    longitude: float


class LiveLocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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


class ReviewSummary(BaseModel):
    average_stars: float
    total_reviews: int
    reviews: list[ReviewOut]


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


# ---- Notifications ----

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    type: str
    title: Optional[str] = None
    body: Optional[str] = None
    channel: Optional[str] = None
    status: str
    created_at: datetime
