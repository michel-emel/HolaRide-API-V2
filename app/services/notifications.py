from app import models
from app.logging_config import get_logger

logger = get_logger("notifications")


def notify_user(db, user_id, type_: str, title: str, body: str, channel: str = "push") -> None:
    """
    DEV STUB — logs the notification to the `notifications` table and
    to your terminal, instead of actually sending a push/SMS/WhatsApp
    message. Swap the logger call for a real provider later; nothing
    that calls this function needs to change.
    """
    notif = models.Notification(
        user_id=user_id, type=type_, title=title, body=body, channel=channel, status="sent"
    )
    db.add(notif)
    db.commit()
    logger.info(f"[DEV NOTIFY] -> user {user_id} via {channel}: {title} | {body}")
