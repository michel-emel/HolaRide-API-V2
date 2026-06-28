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


def _all_participant_ids(db: Session, trip: models.Trip) -> List[UUID]:
    """Driver + every passenger who's reached paid/completed on this trip — used to clear
    everyone's 'hidden' flag when a new message arrives (see send_message below)."""
    ids = [trip.driver_id]
    passenger_rows = (
        db.query(models.Booking.passenger_id)
        .filter(models.Booking.trip_id == trip.id, models.Booking.status.in_(("paid", "completed")))
        .distinct()
        .all()
    )
    ids.extend(row[0] for row in passenger_rows)
    return ids


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
    (booking requests, acceptances, rejections). Only the driver and paid passengers can see
    it. Stays readable forever, including after the trip is completed or cancelled — only
    SENDING gets blocked once a trip is finished, not reading (see send_message below)."""
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
    """
    Sends a message in a trip's group chat. Same access rule as
    reading: only the driver and paid passengers — but on top of that,
    sending (not reading) is blocked once the trip is settled
    (completed or cancelled). The conversation stays fully readable
    forever; it just becomes a closed record once the trip is done,
    same idea as an archived thread.

    Sending also clears the "hidden" flag (see hide_chat below) for
    every participant on this trip — if someone had removed this chat
    from their own list and a real new message comes in, it should
    reappear for them, the same way WhatsApp resurfaces a deleted chat
    when a new message arrives.
    """
    trip = _require_participant(db, trip_id, user)
    if trip.status in ("completed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail="This trip is finished — you can still read the conversation, but can't send new messages.",
        )
    chat = get_or_create_chat(db, trip.id)
    message = models.Message(chat_id=chat.id, sender_id=user.id, content=payload.content, message_type="text")
    db.add(message)

    participant_ids = _all_participant_ids(db, trip)
    db.query(models.HiddenChat).filter(
        models.HiddenChat.trip_id == trip.id,
        models.HiddenChat.user_id.in_(participant_ids),
    ).delete(synchronize_session=False)

    db.commit()
    db.refresh(message)
    return _to_message_out(db, message)


@router.delete("/{trip_id}/chat/messages/{message_id}", response_model=schemas.MessageOut)
def delete_message(
    trip_id: UUID,
    message_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """
    Deletes ONE message — only the person who sent it can delete it,
    nobody else's. This is a soft delete, like WhatsApp: the message
    row stays (so the conversation's flow/order isn't broken), but its
    content is cleared and message_type becomes "deleted" so the app
    can show "This message was deleted" in its place. Works even after
    the trip is completed/cancelled — deleting your own message is
    still allowed in a read-only/archived conversation.
    """
    trip = _require_participant(db, trip_id, user)
    chat = get_or_create_chat(db, trip.id)
    message = (
        db.query(models.Message)
        .filter(models.Message.id == message_id, models.Message.chat_id == chat.id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.sender_id != user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own messages")
    message.content = None
    message.message_type = "deleted"
    db.commit()
    db.refresh(message)
    return _to_message_out(db, message)


@router.post("/{trip_id}/chat/hide")
def hide_chat(trip_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """
    Removes this trip's chat from the CALLER's own chat list only —
    like WhatsApp's "Delete Chat". The other participant(s) keep their
    side of the conversation completely untouched; nothing is actually
    deleted server-side. If anyone sends a new message in this chat
    afterward, it automatically reappears for whoever hid it (see
    send_message above) — same as WhatsApp resurfacing a deleted chat
    on new activity.
    """
    trip = _require_participant(db, trip_id, user)
    existing = (
        db.query(models.HiddenChat)
        .filter(models.HiddenChat.trip_id == trip.id, models.HiddenChat.user_id == user.id)
        .first()
    )
    if not existing:
        db.add(models.HiddenChat(user_id=user.id, trip_id=trip.id))
        db.commit()
    return {"status": "hidden"}


@router.get("/hidden-chats")
def list_hidden_chats(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Returns the trip_ids whose chat the caller has hidden from their own list — the
    Chat inbox (built client-side from bookings + driver trips) filters these out."""
    rows = db.query(models.HiddenChat.trip_id).filter(models.HiddenChat.user_id == user.id).all()
    return {"trip_ids": [str(row[0]) for row in rows]}