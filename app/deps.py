from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.security import decode_token

# HTTPBearer makes the /docs "Authorize" button show a single box to
# paste your access_token into — NOT a username/password form. (The
# previous OAuth2PasswordBearer scheme rendered as a login form even
# though this app has no usernames or passwords at all — that mismatch
# is what was confusing on the /docs page.)
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    token = credentials.credentials
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def require_role(role: str):
    """Use as: Depends(require_role("admin")) — admin is the only fixed role left."""
    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role != role:
            raise HTTPException(status_code=403, detail=f"This action requires role: {role}")
        return user
    return checker


def require_driver():
    """
    Use as: Depends(require_driver()) on any endpoint only someone
    currently able to drive can call. "Able to drive" means owning at
    least one admin-approved vehicle — NOT a fixed role from signup.
    Anyone (a passenger today, the same person tomorrow) becomes a
    driver the moment they register a vehicle and admin approves it.
    """
    def checker(
        user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> models.User:
        has_approved_vehicle = (
            db.query(models.Vehicle)
            .filter(models.Vehicle.driver_id == user.id, models.Vehicle.verification_status == "approved")
            .first()
        )
        if not has_approved_vehicle:
            raise HTTPException(
                status_code=403,
                detail="You need at least one admin-approved vehicle to do this. "
                       "Register one with POST /drivers/me/vehicle first.",
            )
        return user
    return checker
