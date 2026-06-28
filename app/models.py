"""
SQLAlchemy models describing tables that ALREADY EXIST in your database
(created by 001_schema.sql). This file does not create anything — it
just gives Python a way to read/write rows in those tables.

Only the tables needed for Auth + Trips + Bookings are mapped here.
When you build Cancellations, Payments, Payouts, Chat, etc., add a
class for each new table the same way — match the table/column names
exactly to what's in 001_schema.sql.
"""
import uuid

from sqlalchemy import (
    Column, String, Boolean, Integer, Numeric, Date, Time, ForeignKey, Text, text
)
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP, ARRAY

from app.database import Base


def uuid_pk():
    return Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


class User(Base):
    __tablename__ = "users"
    id = uuid_pk()
    phone_number = Column(String, unique=True, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    role = Column(String, nullable=False)
    phone_verified = Column(Boolean, nullable=False, server_default=text("false"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class DriverProfile(Base):
    __tablename__ = "driver_profiles"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    reliability_score = Column(Numeric, nullable=False, server_default=text("100"))
    identity_verified = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class City(Base):
    __tablename__ = "cities"
    id = uuid_pk()
    name = Column(String, unique=True, nullable=False)


class Location(Base):
    __tablename__ = "locations"
    id = uuid_pk()
    city_id = Column(UUID(as_uuid=True), ForeignKey("cities.id"), nullable=False)
    name = Column(String, nullable=False)


class VehicleCategory(Base):
    __tablename__ = "vehicle_categories"
    id = uuid_pk()
    name = Column(String, unique=True, nullable=False)
    description = Column(String)


class Vehicle(Base):
    __tablename__ = "vehicles"
    id = uuid_pk()
    driver_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    brand = Column(String, nullable=False)
    model = Column(String, nullable=False)
    year = Column(Integer)
    color = Column(String)
    plate_number = Column(String, unique=True, nullable=False)
    total_seats = Column(Integer, nullable=False)
    vehicle_category_id = Column(UUID(as_uuid=True), ForeignKey("vehicle_categories.id"))
    verification_status = Column(String, nullable=False, server_default=text("'pending'"))
    photo_urls = Column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Route(Base):
    __tablename__ = "routes"
    id = uuid_pk()
    origin_city_id = Column(UUID(as_uuid=True), ForeignKey("cities.id"), nullable=False)
    destination_city_id = Column(UUID(as_uuid=True), ForeignKey("cities.id"), nullable=False)


class RoutePricing(Base):
    __tablename__ = "route_pricing"
    id = uuid_pk()
    route_id = Column(UUID(as_uuid=True), ForeignKey("routes.id"), nullable=False)
    vehicle_category_id = Column(UUID(as_uuid=True), ForeignKey("vehicle_categories.id"), nullable=False)
    price_per_seat = Column(Numeric, nullable=False)


class CancellationPolicyTier(Base):
    __tablename__ = "cancellation_policy_tiers"
    id = uuid_pk()
    min_hours_before = Column(Integer, nullable=False)
    max_hours_before = Column(Integer)
    fee_percentage = Column(Numeric, nullable=False)


class Trip(Base):
    __tablename__ = "trips"
    id = uuid_pk()
    driver_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=False)
    route_id = Column(UUID(as_uuid=True), ForeignKey("routes.id"), nullable=False)
    departure_location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"), nullable=False)
    destination_location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"), nullable=False)
    departure_date = Column(Date, nullable=False)
    departure_time = Column(Time, nullable=False)
    available_seats = Column(Integer, nullable=False)
    price_per_seat = Column(Numeric, nullable=False)
    status = Column(String, nullable=False, server_default=text("'draft'"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Booking(Base):
    __tablename__ = "bookings"
    id = uuid_pk()
    trip_id = Column(UUID(as_uuid=True), ForeignKey("trips.id"), nullable=False)
    passenger_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    seats_booked = Column(Integer, nullable=False)
    price_total = Column(Numeric, nullable=False)
    payment_type = Column(String, nullable=False, server_default=text("'full'"))
    amount_paid = Column(Numeric, nullable=False, server_default=text("0"))
    outstanding_balance = Column(Numeric, nullable=False, server_default=text("0"))
    status = Column(String, nullable=False, server_default=text("'pending_driver_acceptance'"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Cancellation(Base):
    __tablename__ = "cancellations"
    id = uuid_pk()
    booking_id = Column(UUID(as_uuid=True), ForeignKey("bookings.id"), nullable=False)
    cancelled_by = Column(String, nullable=False)
    reason = Column(String)
    fee_charged = Column(Numeric, nullable=False, server_default=text("0"))
    refund_amount = Column(Numeric, nullable=False, server_default=text("0"))
    rebooked_to = Column(UUID(as_uuid=True), ForeignKey("bookings.id"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class DriverReliabilityLog(Base):
    __tablename__ = "driver_reliability_log"
    id = uuid_pk()
    driver_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    event_type = Column(String, nullable=False)
    points_impact = Column(Numeric, nullable=False)
    related_trip_id = Column(UUID(as_uuid=True), ForeignKey("trips.id"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Payment(Base):
    __tablename__ = "payments"
    id = uuid_pk()
    booking_id = Column(UUID(as_uuid=True), ForeignKey("bookings.id"), nullable=False)
    provider = Column(String, nullable=False)
    provider_transaction_id = Column(String)
    amount = Column(Numeric, nullable=False)
    purpose = Column(String, nullable=False, server_default=text("'full'"))
    status = Column(String, nullable=False, server_default=text("'pending'"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Payout(Base):
    __tablename__ = "payouts"
    id = uuid_pk()
    driver_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    trip_id = Column(UUID(as_uuid=True), ForeignKey("trips.id"), nullable=False)
    provider = Column(String, nullable=False)
    provider_payout_id = Column(String)
    amount = Column(Numeric, nullable=False)
    status = Column(String, nullable=False, server_default=text("'pending'"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Notification(Base):
    __tablename__ = "notifications"
    id = uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    type = Column(String, nullable=False)
    title = Column(String)
    body = Column(String)
    channel = Column(String)
    status = Column(String, nullable=False, server_default=text("'pending'"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class TripChat(Base):
    __tablename__ = "trip_chats"
    id = uuid_pk()
    trip_id = Column(UUID(as_uuid=True), ForeignKey("trips.id"), nullable=False, unique=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Message(Base):
    __tablename__ = "messages"
    id = uuid_pk()
    chat_id = Column(UUID(as_uuid=True), ForeignKey("trip_chats.id"), nullable=False)
    sender_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))  # null for pure system messages
    content = Column(String)
    message_type = Column(String, nullable=False, server_default=text("'text'"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class LiveLocation(Base):
    __tablename__ = "live_locations"
    id = uuid_pk()
    trip_id = Column(UUID(as_uuid=True), ForeignKey("trips.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    latitude = Column(Numeric, nullable=False)
    longitude = Column(Numeric, nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class SOSAlert(Base):
    __tablename__ = "sos_alerts"
    id = uuid_pk()
    trip_id = Column(UUID(as_uuid=True), ForeignKey("trips.id"), nullable=False)
    triggered_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    latitude = Column(Numeric)
    longitude = Column(Numeric)
    emergency_contact_notified = Column(Boolean, nullable=False, server_default=text("false"))
    status = Column(String, nullable=False, server_default=text("'open'"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Review(Base):
    __tablename__ = "reviews"
    id = uuid_pk()
    trip_id = Column(UUID(as_uuid=True), ForeignKey("trips.id"), nullable=False)
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reviewee_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reviewer_role = Column(String, nullable=False)
    stars = Column(Integer, nullable=False)
    comment = Column(String)
    emoji_reaction = Column(String)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class Report(Base):
    __tablename__ = "reports"
    id = uuid_pk()
    reporter_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reported_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    trip_id = Column(UUID(as_uuid=True), ForeignKey("trips.id"))
    category = Column(String)
    description = Column(String)
    status = Column(String, nullable=False, server_default=text("'open'"))
    admin_notes = Column(String)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))
    resolved_at = Column(TIMESTAMP(timezone=True))


class DeviceToken(Base):
    __tablename__ = "device_tokens"
    id = uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token = Column(String, nullable=False)
    platform = Column(String)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class OTPCode(Base):
    """
    NOTE: this table does NOT exist in 001_schema.sql yet — it's the
    small addition mentioned in the API design doc. Run this before
    starting the server for the first time:

    create table otp_codes (
      id          uuid primary key default gen_random_uuid(),
      phone_number text not null,
      code_hash   text not null,
      expires_at  timestamptz not null,
      attempts    int not null default 0,
      created_at  timestamptz not null default now()
    );
    create index idx_otp_phone on otp_codes(phone_number);
    """
    __tablename__ = "otp_codes"
    id = uuid_pk()
    phone_number = Column(String, nullable=False)
    code_hash = Column(String, nullable=False)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))


class HiddenChat(Base):
    """
    Created by alembic migration 0007_hidden_chats.py — tracks which
    trip-chats a user has removed from their OWN chat list, like
    WhatsApp's "Delete Chat". Doesn't affect anyone else's copy of the
    conversation, and doesn't touch the messages table at all; it's
    purely a per-user visibility flag, cleared automatically the next
    time a new message is sent in that chat (see send_message in
    app/routers/chat.py).
    """
    __tablename__ = "hidden_chats"
    id = uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    trip_id = Column(UUID(as_uuid=True), ForeignKey("trips.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))