from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.logging_config import get_logger
from app.services import notifications, payments_provider

router = APIRouter(tags=["payments"])
logger = get_logger("payments")


def _confirm_payment_success(db: Session, payment: models.Payment) -> None:
    """Called once a payment is CONFIRMED complete (via webhook or polling)."""
    payment.status = "success"
    db.commit()

    booking = db.query(models.Booking).filter(models.Booking.id == payment.booking_id).first()
    booking.amount_paid = float(booking.amount_paid) + float(payment.amount)
    if payment.purpose == "balance_settlement":
        booking.outstanding_balance = 0
    if booking.status == "pending_payment":
        booking.status = "paid"
    db.commit()

    # Notify the passenger their payment went through.
    notifications.notify_user(
        db, booking.passenger_id, "payment_success", "Payment confirmed",
        f"Your payment of {float(payment.amount):.0f} FCFA was confirmed. You're all set for your trip!",
        reference_id=booking.trip_id,
    )

    # Notify the driver that this passenger has paid — they need to know
    # so they can plan their seat count and confirm the passenger's spot.
    trip = db.query(models.Trip).filter(models.Trip.id == booking.trip_id).first()
    if trip:
        passenger = db.query(models.User).filter(models.User.id == booking.passenger_id).first()
        passenger_name = (
            f"{passenger.first_name or ''} {passenger.last_name or ''}".strip()
            or passenger.phone_number
            if passenger else "A passenger"
        )
        notifications.notify_user(
            db, trip.driver_id, "passenger_paid", "Passenger payment confirmed",
            f"{passenger_name} has paid {float(payment.amount):.0f} FCFA for their seat on your trip.",
            reference_id=booking.trip_id,
        )


def _mark_payment_failed(db: Session, payment: models.Payment) -> None:
    """Called once a payment is CONFIRMED failed (via webhook or polling) — notifies the passenger to retry."""
    payment.status = "failed"
    db.commit()
    booking = db.query(models.Booking).filter(models.Booking.id == payment.booking_id).first()
    notifications.notify_user(
        db, booking.passenger_id, "payment_failed", "Payment failed",
        "Your Mobile Money payment didn't go through. Please try again.",
    )


@router.post("/bookings/{booking_id}/initiate-payment")
def initiate_payment(
    booking_id: UUID,
    db: Session = Depends(get_db),
    passenger: models.User = Depends(get_current_user),
):
    """
    Starts a real PawaPay Mobile Money charge for whatever's owed on
    this booking (full price, or 80% for a partial-payment booking).
    Returns immediately with status "pending" — the customer still
    has to approve it on their phone. Poll GET .../payment-status or
    wait for the webhook to find out the real outcome.
    """
    booking = (
        db.query(models.Booking)
        .filter(models.Booking.id == booking_id, models.Booking.passenger_id == passenger.id)
        .first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status != "pending_payment":
        raise HTTPException(status_code=400, detail=f"Booking is already {booking.status}")

    amount_due = float(booking.price_total) - float(booking.outstanding_balance)
    purpose = "initial_80" if booking.payment_type == "partial_80" else "full"

    try:
        result = payments_provider.charge(passenger.phone_number, amount_due)
    except Exception as exc:
        logger.error(f"PawaPay charge failed for booking {booking_id}: {exc}")
        raise HTTPException(status_code=502, detail="Could not reach the Mobile Money provider. Try again shortly.")

    payment = models.Payment(
        booking_id=booking.id,
        provider="pawapay",
        provider_transaction_id=result["provider_transaction_id"],
        amount=amount_due,
        purpose=purpose,
        status="pending" if result["status"] == "pending" else "failed",
    )
    db.add(payment)
    db.commit()

    return {
        "booking_id": booking.id,
        "payment_status": payment.status,
        "message": (
            "Check your phone and approve the Mobile Money prompt. "
            "Poll GET /bookings/{booking_id}/payment-status to see when it's confirmed."
            if payment.status == "pending"
            else "Payment request was rejected immediately."
        ),
    }


@router.post("/bookings/{booking_id}/pay-balance")
def pay_balance(
    booking_id: UUID,
    db: Session = Depends(get_db),
    passenger: models.User = Depends(get_current_user),
):
    """
    Charges the remaining 20% on a partial-payment booking. Same
    pending/poll/webhook pattern as initiate-payment. Fails immediately
    if there's nothing outstanding (e.g. already a full-payment booking).
    """
    booking = (
        db.query(models.Booking)
        .filter(models.Booking.id == booking_id, models.Booking.passenger_id == passenger.id)
        .first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if float(booking.outstanding_balance) <= 0:
        raise HTTPException(status_code=400, detail="Nothing outstanding on this booking")

    amount_due = float(booking.outstanding_balance)
    try:
        result = payments_provider.charge(passenger.phone_number, amount_due)
    except Exception as exc:
        logger.error(f"PawaPay charge failed for booking {booking_id} balance: {exc}")
        raise HTTPException(status_code=502, detail="Could not reach the Mobile Money provider. Try again shortly.")

    payment = models.Payment(
        booking_id=booking.id,
        provider="pawapay",
        provider_transaction_id=result["provider_transaction_id"],
        amount=amount_due,
        purpose="balance_settlement",
        status="pending" if result["status"] == "pending" else "failed",
    )
    db.add(payment)
    db.commit()

    return {"booking_id": booking.id, "payment_status": payment.status}


@router.get("/bookings/{booking_id}/payment-status")
def get_payment_status(
    booking_id: UUID,
    db: Session = Depends(get_db),
    passenger: models.User = Depends(get_current_user),
):
    """
    Have the Flutter app call this every few seconds after
    initiate-payment/pay-balance, until payment_status is no longer
    'pending'. This is the polling fallback for when you haven't set
    up a callback URL — see app/services/payments_provider.py.
    """
    payment = (
        db.query(models.Payment)
        .filter(models.Payment.booking_id == booking_id, models.Payment.status == "pending")
        .order_by(models.Payment.created_at.desc())
        .first()
    )
    if not payment:
        booking = db.query(models.Booking).filter(models.Booking.id == booking_id).first()
        return {"payment_status": "none_pending", "booking_status": booking.status if booking else None}

    provider_status = payments_provider.check_deposit_status(payment.provider_transaction_id)
    if provider_status == "COMPLETED":
        _confirm_payment_success(db, payment)
    elif provider_status == "FAILED":
        _mark_payment_failed(db, payment)

    db.refresh(payment)
    return {"payment_status": payment.status}


@router.post("/bookings/{booking_id}/dev-force-paid")
def dev_force_paid(
    booking_id: UUID,
    db: Session = Depends(get_db),
    passenger: models.User = Depends(get_current_user),
):
    """
    DEV-ONLY. Instantly marks a booking "paid" without touching PawaPay
    at all — the in-app equivalent of quick_test.py's force_mark_paid(),
    just reachable from the Flutter app for convenience while real
    Mobile Money integration is still being worked out.

    404s immediately, as if this route doesn't exist, unless
    PAYMENT_DEV_MODE=true — and that flag is forcibly disabled in
    production regardless of .env (see app/config.py). This must never
    be reachable for a real user paying for a real trip; the 404 here
    is the actual security boundary, not just a hidden button in the app.
    """
    if not settings.payment_dev_mode:
        raise HTTPException(status_code=404, detail="Not found")

    booking = (
        db.query(models.Booking)
        .filter(models.Booking.id == booking_id, models.Booking.passenger_id == passenger.id)
        .first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status not in ("pending_payment", "paid"):
        raise HTTPException(status_code=400, detail=f"Booking is {booking.status} — nothing to settle")

    booking.status = "paid"
    booking.amount_paid = float(booking.price_total)
    booking.outstanding_balance = 0
    db.commit()

    logger.warning(f"[DEV] booking {booking_id} force-marked paid via dev-force-paid endpoint")
    return {"booking_id": booking.id, "status": booking.status}


@router.post("/payments/webhook/pawapay")
async def pawapay_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Configure this URL in your PawaPay sandbox dashboard under
    Developers > Callback URLs. For local testing, expose your
    localhost with ngrok (or similar) first, since PawaPay needs to
    reach this URL from the internet — it can't call 127.0.0.1.
    """
    payload = await request.json()
    transaction_id = payload.get("depositId") or payload.get("payoutId")
    status = payload.get("status")

    if not transaction_id:
        raise HTTPException(status_code=400, detail="Missing depositId/payoutId in callback")

    payment = (
        db.query(models.Payment)
        .filter(models.Payment.provider_transaction_id == transaction_id)
        .first()
    )
    if payment:
        if status == "COMPLETED":
            _confirm_payment_success(db, payment)
        elif status == "FAILED":
            _mark_payment_failed(db, payment)
        return {"received": True}

    payout = (
        db.query(models.Payout)
        .filter(models.Payout.provider_payout_id == transaction_id)
        .first()
    )
    if payout:
        payout.status = "success" if status == "COMPLETED" else "failed" if status == "FAILED" else payout.status
        db.commit()
        return {"received": True}

    logger.warning(f"PawaPay webhook for unknown transaction_id={transaction_id}")
    return {"received": True}