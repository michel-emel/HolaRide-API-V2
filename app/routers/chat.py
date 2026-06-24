from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import get_current_user
from app.services.chat_service import get_or_create_chat
from app.services.trip_access import get_participant_role

router = APIRouter(prefix="/trips", tags=["chat"])


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


def _to_message_out(db: Session, message: models.Message) -> schemas.MessageOut:
    """
    Joins in the sender's name. Necessary because this can be a real
    group chat with several different passengers plus the driver all
    in the same conversation — without a name attached, there'd be no
    way to tell which "other" person sent a given message once there's
    more than one participant besides yourself.
    """
    sender = db.query(models.User).filter(models.User.id == message.sender_id).first() if message.sender_id else None
    return schemas.MessageOut(
        id=message.id,
        chat_id=message.chat_id,
        sender_id=message.sender_id,
        content=message.content,
        message_type=message.message_type,
        created_at=message.created_at,
        sender_first_name=sender.first_name if sender else None,
        sender_last_name=sender.last_name if sender else None,
    )


@router.get("/{trip_id}/chat/messages", response_model=List[schemas.MessageOut])
def list_messages(trip_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Reads the full message history for a trip — including automated system messages
    (booking requests, acceptances, rejections). Only the driver and paid passengers can see it."""
    trip = _require_participant(db, trip_id, user)
    chat = get_or_create_chat(db, trip.id)
    messages = (
        db.query(models.Message)
        .filter(models.Message.chat_id == chat.id)
        .order_by(models.Message.created_at)
        .all()
    )
    return [_to_message_out(db, m) for m in messages]


@router.post("/{trip_id}/chat/messages", response_model=schemas.MessageOut)
def send_message(
    trip_id: UUID,
    payload: schemas.MessageCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Sends a message in a trip's group chat. Same access rule as reading: only the driver and paid passengers."""
    trip = _require_participant(db, trip_id, user)
    chat = get_or_create_chat(db, trip.id)
    message = models.Message(chat_id=chat.id, sender_id=user.id, content=payload.content, message_type="text")
    db.add(message)
    db.commit()
    db.refresh(message)
    return _to_message_out(db, message)