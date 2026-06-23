from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import get_current_user

router = APIRouter(tags=["users"])


@router.get("/me", response_model=schemas.UserOut)
def get_me(user: models.User = Depends(get_current_user)):
    """Returns the current logged-in user's own profile."""
    return user


@router.patch("/me", response_model=schemas.UserOut)
def update_me(
    payload: schemas.UserUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """For editing a name set wrong at registration, or filling it in if it was skipped."""
    if payload.first_name is not None:
        user.first_name = payload.first_name
    if payload.last_name is not None:
        user.last_name = payload.last_name
    db.commit()
    db.refresh(user)
    return user


@router.get("/me/notifications", response_model=List[schemas.NotificationOut])
def my_notifications(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Lists the current user's notifications, most recent first (capped at 50)."""
    return (
        db.query(models.Notification)
        .filter(models.Notification.user_id == user.id)
        .order_by(models.Notification.created_at.desc())
        .limit(50)
        .all()
    )
