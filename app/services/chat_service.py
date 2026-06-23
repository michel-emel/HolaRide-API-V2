from sqlalchemy.orm import Session

from app import models


def get_or_create_chat(db: Session, trip_id) -> models.TripChat:
    """Trip chats are created lazily on first message/read, not at trip creation."""
    chat = db.query(models.TripChat).filter(models.TripChat.trip_id == trip_id).first()
    if not chat:
        chat = models.TripChat(trip_id=trip_id)
        db.add(chat)
        db.commit()
        db.refresh(chat)
    return chat


def post_system_message(db: Session, trip_id, content: str) -> models.Message:
    """
    Posts an automated message into a trip's chat (sender_id is null,
    message_type='system') — e.g. "Aminata requested 2 seats." The
    driver sees these immediately (always a chat participant on their
    own trip); a passenger only sees the history once their booking
    reaches 'paid', same access rule as everything else in chat.
    """
    chat = get_or_create_chat(db, trip_id)
    message = models.Message(chat_id=chat.id, sender_id=None, content=content, message_type="system")
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
