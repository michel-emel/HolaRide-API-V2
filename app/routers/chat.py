from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import get_current_user
from app.services.trip_access import get_participant_role

router = APIRouter(prefix="/trips", tags=["chat"])


def _get_or_create_chat(db: Session, trip_id: UUID) -> models.TripChat:
    """Internal helper. Trip chats are created lazily on first message/read, not at trip creation."""
    chat = db.query(models.TripChat).filter(models.TripChat.trip_id == trip_id).first()
    if not chat:
        chat = models.TripChat(trip_id=trip_id)
        db.add(chat)
        db.commit()
        db.refresh(chat)
    return chat


def _require_participant(db: Session, trip_id: UUID, user: models.User) -> models.Trip:
    """Internal helper. Raises 403 unless the user is the driver or a paid passenger on this trip."""
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if not get_participant_role(db, trip, user):
        raise HTTPException(
            status_code=403,
            detail="Chat is only available to the driver and passengers who've paid for this trip",
        )
    return trip


@router.get("/{trip_id}/chat/messages", response_model=List[schemas.MessageOut])
def list_messages(trip_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Reads the full message history for a trip. Only the driver and paid passengers can see it."""
    trip = _require_participant(db, trip_id, user)
    chat = _get_or_create_chat(db, trip.id)
    return db.query(models.Message).filter(models.Message.chat_id == chat.id).order_by(models.Message.created_at).all()


@router.post("/{trip_id}/chat/messages", response_model=schemas.MessageOut)
def send_message(
    trip_id: UUID,
    payload: schemas.MessageCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Sends a message in a trip's group chat. Same access rule as reading: only the driver and paid passengers."""
    trip = _require_participant(db, trip_id, user)
    chat = _get_or_create_chat(db, trip.id)
    message = models.Message(chat_id=chat.id, sender_id=user.id, content=payload.content, message_type="text")
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
