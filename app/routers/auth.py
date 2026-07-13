from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import settings
from app.database import get_db
from app.rate_limit import enforce_rate_limit, otp_request_limiter, otp_verify_limiter
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_otp_code,
    hash_otp,
    verify_otp_hash,
)
from app.services.sms import send_otp_sms

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/otp/request")
def request_otp(payload: schemas.OTPRequest, request: Request, db: Session = Depends(get_db)):
    """
    Sends a 6-digit OTP to the phone number.
    Accepts first_name (required) and last_name (optional) — stored
    temporarily in otp_codes so that verify_otp can create the account
    with the correct name without needing a separate PATCH /me call.
    No user is created here — only when the OTP is successfully verified.
    """
    enforce_rate_limit(otp_request_limiter, request)

    code = generate_otp_code()
    otp_row = models.OTPCode(
        phone_number=payload.phone_number,
        code_hash=hash_otp(code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expire_minutes),
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    db.add(otp_row)
    db.commit()

    send_otp_sms(payload.phone_number, code)

    response = {"message": "OTP sent"}
    if settings.otp_dev_mode:
        response["dev_otp_code"] = code
    return response


@router.post("/otp/verify")
def verify_otp(payload: schemas.OTPVerify, request: Request, db: Session = Depends(get_db)):
    """
    Verifies the OTP code.
    - For NEW users: creates the account using the name stored in
      otp_codes at request time. No user exists in the DB until this
      point — abandoning before verification leaves no trace.
    - For EXISTING users: just returns a new token pair, name is ignored.
    """
    enforce_rate_limit(otp_verify_limiter, request)

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
    is_new_user = user is None
    if not user:
        user = models.User(
            phone_number=payload.phone_number,
            role="passenger",
            phone_verified=True,
            first_name=otp_row.first_name,
            last_name=otp_row.last_name,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.phone_verified = True
        db.commit()

    db.delete(otp_row)
    db.commit()

    return {
        "access_token":  create_access_token(str(user.id), user.role),
        "refresh_token": create_refresh_token(str(user.id), user.role),
        "token_type":    "bearer",
        "is_new_user":   is_new_user,
    }


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
