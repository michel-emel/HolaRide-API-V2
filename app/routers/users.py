from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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


@router.patch("/me/notifications/{notification_id}/read", response_model=schemas.NotificationOut)
def mark_notification_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Marks a single notification as read. Idempotent — marking an
    already-read notification does nothing visible. Only works on the
    caller's own notifications."""
    notif = (
        db.query(models.Notification)
        .filter(models.Notification.id == notification_id, models.Notification.user_id == user.id)
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not notif.read_at:
        notif.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notif)
    return notif


@router.patch("/me/notifications/read-all")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Marks ALL of the caller's unread notifications as read at once."""
    db.query(models.Notification).filter(
        models.Notification.user_id == user.id,
        models.Notification.read_at.is_(None),
    ).update({models.Notification.read_at: datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()
    return {"status": "ok"}


@router.get("/me/notifications/unread-count")
def unread_notification_count(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Returns just the count of unread notifications — used by the
    bell badge on Home."""
    count = (
        db.query(models.Notification)
        .filter(models.Notification.user_id == user.id, models.Notification.read_at.is_(None))
        .count()
    )
    return {"count": count}

@router.delete("/me/notifications/{notification_id}")
def delete_notification(
    notification_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Deletes a single notification. Only works on the caller's own
    notifications."""
    notif = (
        db.query(models.Notification)
        .filter(models.Notification.id == notification_id, models.Notification.user_id == user.id)
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    db.delete(notif)
    db.commit()
    return {"status": "deleted"}


@router.delete("/me/notifications")
def delete_all_notifications(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Deletes ALL of the caller's notifications at once."""
    db.query(models.Notification).filter(models.Notification.user_id == user.id).delete(
        synchronize_session=False
    )
    db.commit()
    return {"status": "ok"}