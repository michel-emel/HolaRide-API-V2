import sys
path = sys.argv[1]
with open(path) as f:
    content = f.read()

# 1. Replace import
content = content.replace(
    "from app.services import notifications, payments_provider",
    "from app.services import notifications, hrskills_pay"
)

# 2. Replace initiate-payment charge call
old_charge = """    try:
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
    }"""

new_charge = """    try:
        result = hrskills_pay.initiate_cashin(
            phone=passenger.phone_number,
            amount=amount_due,
            booking_id=str(booking.id),
            description=f"HolaRide booking #{str(booking.id)[:8]}",
        )
    except Exception as exc:
        logger.error(f"HR-Skills Pay charge failed for booking {booking_id}: {exc}")
        raise HTTPException(status_code=502, detail="Could not reach the Mobile Money provider. Try again shortly.")
    payment = models.Payment(
        booking_id=booking.id,
        provider="hrskills_pay",
        provider_transaction_id=result["reference"],
        amount=amount_due,
        purpose=purpose,
        status="pending" if result["status"] in ("PENDING", "pending") else "failed",
    )
    db.add(payment)
    db.commit()
    return {
        "booking_id": booking.id,
        "reference": result["reference"],
        "payment_status": payment.status,
        "message": (
            "Check your phone and approve the Mobile Money prompt."
            if payment.status == "pending"
            else "Payment request was rejected immediately."
        ),
    }"""

content = content.replace(old_charge, new_charge)

# 3. Replace pay-balance charge call
old_balance = """    try:
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
    )"""

new_balance = """    try:
        result = hrskills_pay.initiate_cashin(
            phone=passenger.phone_number,
            amount=amount_due,
            booking_id=str(booking.id),
            description=f"HolaRide balance #{str(booking.id)[:8]}",
        )
    except Exception as exc:
        logger.error(f"HR-Skills Pay charge failed for booking {booking_id} balance: {exc}")
        raise HTTPException(status_code=502, detail="Could not reach the Mobile Money provider. Try again shortly.")

    payment = models.Payment(
        booking_id=booking.id,
        provider="hrskills_pay",
        provider_transaction_id=result["reference"],
        amount=amount_due,
        purpose="balance_settlement",
        status="pending" if result["status"] in ("PENDING", "pending") else "failed",
    )"""

content = content.replace(old_balance, new_balance)

# 4. Replace payment status check
old_status = "    provider_status = payments_provider.check_deposit_status(payment.provider_transaction_id)"
new_status = """    try:
        provider_status = hrskills_pay.get_payment_status(payment.provider_transaction_id)
    except Exception as exc:
        logger.error(f"HR-Skills Pay status check failed: {exc}")
        return {"payment_status": "pending"}"""

content = content.replace(old_status, new_status)

# 5. Fix status comparison (hrskills uses SUCCESS/FAILED not COMPLETED/FAILED)
content = content.replace(
    'if provider_status == "COMPLETED":',
    'if provider_status == "SUCCESS":'
)

with open(path, "w") as f:
    f.write(content)

checks = [
    ("hrskills_pay.initiate_cashin", "initiate_cashin call"),
    ("hrskills_pay.get_payment_status", "status check"),
    ('provider="hrskills_pay"', "provider name"),
    ('result["reference"]', "reference key"),
    ('"SUCCESS"', "status comparison"),
]
for k, label in checks:
    print(f"{'✓' if k in content else '✗'} {label}")