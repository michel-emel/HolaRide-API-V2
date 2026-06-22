from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import settings
from app.database import get_db
from app.rate_limit import limiter
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_otp_code,
    hash_otp,
    verify_otp_hash,
)
from app.services.sms import send_otp_sms

# Strict in production (real abuse prevention). Generous in development,
# since testing naturally fires several signups in a row from the same
# machine/IP, and the limiter doesn't know those are different phone
# numbers — it only sees "the same IP, too many requests."
_OTP_REQUEST_LIMIT = "3/minute" if settings.environment == "production" else "30/minute"
_OTP_VERIFY_LIMIT = "10/minute" if settings.environment == "production" else "60/minute"

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/otp/request")
@limiter.limit(_OTP_REQUEST_LIMIT)  # prevents someone spamming your SMS bill or hammering one number
def request_otp(payload: schemas.OTPRequest, request: Request, db: Session = Depends(get_db)):
    """
    Sends a 6-digit code to a phone number. Works the same whether the
    number is new (will become a signup once verified) or existing
    (a login). In dev mode, the code is also returned in the response
    body (dev_otp_code) for easy scripting — never happens in production.
    """
    code = generate_otp_code()
    otp_row = models.OTPCode(
        phone_number=payload.phone_number,
        code_hash=hash_otp(code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expire_minutes),
    )
    db.add(otp_row)
    db.commit()

    send_otp_sms(payload.phone_number, code)

    response = {"message": "OTP sent"}
    if settings.otp_dev_mode:
        # Only ever present in dev mode (forcibly disabled in production —
        # see app/config.py). Lets test scripts read the code directly
        # instead of needing to watch the server's terminal output.
        response["dev_otp_code"] = code
    return response


@router.post("/otp/verify", response_model=schemas.TokenPair)
@limiter.limit(_OTP_VERIFY_LIMIT)  # the attempts-counter inside this function already
                              # blocks brute-forcing one phone's code; this caps
                              # the request rate itself as a second layer
def verify_otp(payload: schemas.OTPVerify, request: Request, db: Session = Depends(get_db)):
    """
    Verifies the code from /otp/request and returns access + refresh
    tokens. If this phone number has never been seen before, this is
    what actually creates the account — first_name/last_name are only
    used on that first call and ignored on every login after.
    """
    otp_row = (
        db.query(models.OTPCode)
        .filter(models.OTPCode.phone_number == payload.phone_number)
        .order_by(models.OTPCode.created_at.desc())
        .first()
    )
    if not otp_row:
        raise HTTPException(status_code=400, detail="No OTP was requested for this number")
    if otp_row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="OTP expired — request a new one")
    if otp_row.attempts >= 5:
        raise HTTPException(status_code=429, detail="Too many wrong attempts — request a new OTP")
    if not verify_otp_hash(payload.code, otp_row.code_hash):
        otp_row.attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Incorrect code")

    user = db.query(models.User).filter(models.User.phone_number == payload.phone_number).first()
    if not user:
        # Everyone signs up the same way now. "role" only still matters
        # to distinguish admin from everyone else — admin accounts are
        # promoted manually (see README), never self-selected here.
        user = models.User(
            phone_number=payload.phone_number,
            role="passenger",
            phone_verified=True,
            first_name=payload.first_name,
            last_name=payload.last_name,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.phone_verified = True
        db.commit()

    db.delete(otp_row)
    db.commit()

    return schemas.TokenPair(
        access_token=create_access_token(str(user.id), user.role),
        refresh_token=create_refresh_token(str(user.id), user.role),
    )


@router.post("/refresh", response_model=schemas.TokenPair)
def refresh_token(payload: schemas.RefreshRequest):
    """Exchanges a still-valid refresh token for a brand new access + refresh token pair."""
    try:
        data = decode_token(payload.refresh_token)
        if data.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    return schemas.TokenPair(
        access_token=create_access_token(data["sub"], data["role"]),
        refresh_token=create_refresh_token(data["sub"], data["role"]),
    )
